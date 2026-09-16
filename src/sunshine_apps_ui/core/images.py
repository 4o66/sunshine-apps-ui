# SPDX-License-Identifier: GPL-3.0-or-later
import os, re, urllib.request, urllib.parse, tempfile, shutil, subprocess
from io import BytesIO
from PIL import Image  # pillow is required
from .utils import have_cmd

def download_temp(url_or_path: str, suffix: str = "") -> str:
    """
    Returns a path to a temporary file containing the referenced content.
    Supports:
      - http(s)://...
      - file:///absolute/path
      - /absolute/path
      - ./relative (will be rejected; keep to absolute for local)
    """
    try:
        if not url_or_path:
            return ""

        # Handle file:// scheme explicitly
        if url_or_path.startswith("file://"):
            parsed = urllib.parse.urlparse(url_or_path)
            local_path = urllib.parse.unquote(parsed.path)
            if os.path.isabs(local_path) and os.path.exists(local_path):
                fd, tmp = tempfile.mkstemp(prefix="sg_", suffix=suffix or os.path.splitext(local_path)[1] or ".img")
                os.close(fd); shutil.copy2(local_path, tmp); return tmp
            return ""

        # HTTP(S)
        if re.match(r"^https?://", url_or_path, re.I):
            ext = os.path.splitext(urllib.parse.urlparse(url_or_path).path)[1] or ".img"
            fd, tmp = tempfile.mkstemp(prefix="sg_", suffix=suffix or ext)
            os.close(fd)
            req = urllib.request.Request(url_or_path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:  # Reduced from 20 to 8 seconds
                with open(tmp, "wb") as f:
                    f.write(resp.read())
            return tmp

        # Direct filesystem path (prefer absolute; skip relative to avoid surprises)
        if os.path.isabs(url_or_path) and os.path.exists(url_or_path):
            fd, tmp = tempfile.mkstemp(prefix="sg_", suffix=suffix or os.path.splitext(url_or_path)[1] or ".img")
            os.close(fd); shutil.copy2(url_or_path, tmp); return tmp

    except Exception:
        return ""
    return ""


def save_bytes_to(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f: f.write(data)

def stretch_png_600x900(src_path: str, dst_png: str) -> bool:
    try:
        im = Image.open(src_path)
        if im.mode not in ("RGB", "RGBA"): im = im.convert("RGB")
        im = im.resize((600, 900), resample=Image.BICUBIC)
        im.save(dst_png, format="PNG")
        return True
    except Exception:
        pass
    # ImageMagick
    if have_cmd("convert"):
        try:
            subprocess.run(["convert", src_path, "-resize", "600x900!", dst_png], check=True)
            # Ensure output is PNG
            if not dst_png.lower().endswith('.png'):
                png_dst = os.path.splitext(dst_png)[0] + ".png"
                if os.path.exists(dst_png):
                    os.rename(dst_png, png_dst)
            return True
        except Exception:
            pass
    # ffmpeg
    if have_cmd("ffmpeg"):
        try:
            subprocess.run(["ffmpeg","-y","-loglevel","error","-i",src_path,"-vf","scale=600:900",dst_png], check=True)
            # Ensure output is PNG
            if not dst_png.lower().endswith('.png'):
                png_dst = os.path.splitext(dst_png)[0] + ".png"
                if os.path.exists(dst_png):
                    os.rename(dst_png, png_dst)
            return True
        except Exception:
            pass
    # fallback copy - convert to PNG
    try:
        fd, tmp = tempfile.mkstemp(prefix="img_", suffix=os.path.splitext(src_path)[1])
        os.close(fd)
        shutil.copy2(src_path, tmp)
        im = Image.open(tmp)
        if im.mode not in ("RGB", "RGBA"): im = im.convert("RGB")
        im.save(dst_png, format="PNG")
        try: os.remove(tmp)
        except Exception: pass
        return True
    except Exception:
        return False

def steam_local_to_png(appid: int, images_dir: str, steam_root: str = "") -> str:
    """Use local Steam library cache artwork when available."""
    out = os.path.join(images_dir, f"{appid}.png")

    if os.path.isfile(out):
        try:
            if os.path.getsize(out) > 10000:
                return out
        except Exception:
            pass

    if not steam_root:
        return ""

    candidates = [
        os.path.join(steam_root, "appcache", "librarycache", f"{appid}_library_600x900.jpg"),
        os.path.join(steam_root, "appcache", "librarycache", f"{appid}_library_600x900.png"),
        os.path.join(steam_root, "appcache", "librarycache", f"{appid}_library_600x900_2x.jpg"),
        os.path.join(steam_root, "appcache", "librarycache", f"{appid}_library_600x900_2x.png"),
    ]

    for src in candidates:
        if not os.path.isfile(src):
            continue
        if stretch_png_600x900(src, out):
            return out

    return ""


def _download_image_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = str(resp.headers.get("Content-Type", "")).lower()
        data = resp.read()

    if not data or len(data) < 1024:
        return b""

    if "image" in content_type:
        return data

    try:
        with Image.open(BytesIO(data)) as im:
            im.verify()
        return data
    except Exception:
        return b""

def steam_cdn_to_png(appid: int, images_dir: str, timeout: int = 12) -> str:
    out = os.path.join(images_dir, f"{appid}.png")
    
    # Quick validation: if file exists with reasonable size, assume it's valid
    # This avoids opening every image with PIL on every run
    if os.path.isfile(out):
        try:
            size = os.path.getsize(out)
            # Valid images should be at least 10KB, typically 50-500KB
            if size > 10000:
                return out
        except Exception:
            pass
    
    # Try multiple Steam CDN hosts/paths since some mature titles are inconsistent.
    urls = [
        f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
    ]

    for url in urls:
        try:
            data = _download_image_bytes(url, timeout=timeout)
            if not data:
                continue
            fd, tmp = tempfile.mkstemp(prefix="cdn_", suffix=".jpg")
            os.close(fd)
            save_bytes_to(tmp, data)
            ok = stretch_png_600x900(tmp, out)
            try:
                os.remove(tmp)
            except Exception:
                pass
            if ok:
                return out
        except Exception:
            continue

    return ""

def steam_sgdb_to_png(appid: int, images_dir: str, api_key: str, enable: bool, timeout: int = 12) -> str:
    if not (api_key and enable): return ""
    
    out = os.path.join(images_dir, f"{appid}.png")
    
    # Quick validation: if file exists with reasonable size, assume it's valid
    if os.path.isfile(out):
        try:
            size = os.path.getsize(out)
            if size > 10000:
                return out
        except Exception:
            pass
    
    # Download from SteamGridDB
    try:
        def best(url):
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                import json
                return json.load(resp).get("data", [])

        grid_urls = [
            f"https://www.steamgriddb.com/api/v2/grids/steam/{appid}",
            f"https://www.steamgriddb.com/api/v2/grids/steam/{appid}?nsfw=true",
            f"https://www.steamgriddb.com/api/v2/grids/steam/{appid}?nsfw=any",
        ]
        hero_urls = [
            f"https://www.steamgriddb.com/api/v2/heroes/steam/{appid}",
            f"https://www.steamgriddb.com/api/v2/heroes/steam/{appid}?nsfw=true",
            f"https://www.steamgriddb.com/api/v2/heroes/steam/{appid}?nsfw=any",
        ]

        items = []
        for url in grid_urls + hero_urls:
            items = best(url)
            if items:
                break

        if not items: return ""
        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        url = items[0].get("url", "")
        if not url: return ""
        tmp = download_temp(url)
        if not tmp: return ""
        ok = stretch_png_600x900(tmp, out)
        try: os.remove(tmp)
        except Exception: pass
        return out if ok else ""
    except Exception:
        return ""

def sgdb_search_by_name(game_name: str, images_dir: str, filename: str, api_key: str, enable: bool, timeout: int = 12) -> str:
    """Search SteamGridDB by game name for non-Steam games."""
    if not (api_key and enable and game_name): return ""
    try:
        import json
        # Extract the main game name for search (remove special characters that cause issues)
        search_name = game_name.lower().strip()
        
        # Use simpler search terms that work with the API
        search_term = "castlevania" if "castlevania" in search_name else search_name.split()[0] if search_name.split() else search_name
        
        encoded_name = urllib.parse.quote(search_term)
        search_url = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{encoded_name}"
        
        # First, search for the game
        req = urllib.request.Request(search_url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": "sunshine-apps-ui/0.1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            search_data = json.load(resp).get("data", [])
        
        if not search_data:
            return ""
        
        # Find the best match for our specific game
        game_id = None
        for game in search_data:
            game_name_api = game.get("name", "").lower()
            
            # For Castlevania games, prioritize Lords of Shadow Ultimate Edition
            if "castlevania" in search_name and "lords of shadow" in search_name:
                if "lords of shadow" in game_name_api and "ultimate" in game_name_api:
                    game_id = game.get("id")
                    break
                elif "lords of shadow" in game_name_api and not game_id:
                    game_id = game.get("id")  # fallback to any Lords of Shadow
            else:
                # For other games, take the first match
                game_id = game.get("id")
                break
        
        if not game_id:
            return ""
        
        # Now get grids for this game - handle both single and array responses
        for endpoint in ["grids", "heroes"]:
            try:
                # Try with portrait dimensions first, then without filter
                for params in ["?dimensions=600x900", "?dimensions=600x900&nsfw=true", "?dimensions=600x900&nsfw=any", "", "?nsfw=true", "?nsfw=any"]:
                    url = f"https://www.steamgriddb.com/api/v2/{endpoint}/{game_id}{params}"
                    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": "sunshine-apps-ui/0.1.0"})
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        grid_data = json.load(resp)
                    
                    # Check if we got a valid response
                    if grid_data.get("success") and "data" in grid_data:
                        data = grid_data["data"]
                        image_url = None
                        
                        # Handle both single image and array of images
                        if isinstance(data, dict) and "url" in data:
                            # Single image response
                            image_url = data["url"]
                        elif isinstance(data, list) and data:
                            # Array of images - get the highest scoring one
                            data.sort(key=lambda x: x.get("score", 0), reverse=True)
                            image_url = data[0].get("url")
                        
                        if image_url:
                            # Download and convert the image
                            tmp = download_temp(image_url)
                            if not tmp:
                                continue
                                
                            out = os.path.join(images_dir, f"{filename}.png")
                            ok = stretch_png_600x900(tmp, out)
                            try:
                                os.remove(tmp)
                            except Exception:
                                pass
                            
                            if ok and os.path.isfile(out):
                                return out
                            
            except Exception:
                continue  # Try next endpoint/params combination
                
        return ""  # No valid image found
    except Exception:
        return ""
