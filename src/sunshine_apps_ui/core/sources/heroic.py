# SPDX-License-Identifier: GPL-3.0-or-later
# importers/heroic.py
# Heroic (Epic/GOG/Amazon/Sideload) importer
# Ports the logic from the monolithic sunshine-import.py into the split architecture.

import os
import re
import json
import time

import glob
import threading
from pathlib import Path
from typing import List, Dict, Any

from ..utils import log, read_json, slugify, yn
from ..images import download_temp, stretch_png_600x900, sgdb_search_by_name
from ..image_downloader import ImageDownloader
from ..reconcile import tag

# How often the Heroic cache build says where it has got to. Short enough that
# the line visibly moves, long enough that saying so is not most of the work.
PROGRESS_EVERY = 1.5


def import_heroic(home: str, conf_dir: str, images_dir: str, settings: Dict[str, Any],
                  report: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    Discover Epic/GOG/Amazon (via Heroic) and Sideload apps and return Sunshine app entries.

    Args:
        home: user home directory
        conf_dir: detected Sunshine config directory (unused here, kept for symmetry)
        images_dir: directory to store Heroic covers (PNG; 600x900)
        settings: environment snapshot for toggles (IMPORT_HEROIC, INCLUDE_SOURCES, BLACKLIST_NAME_REGEX, ...)

    Returns:
        List of Sunshine app dicts.
    """
    if report is None:
        report = {}
    report["status"] = "not_found"

    IMPORT_HEROIC = settings.get("IMPORT_HEROIC", True)
    if isinstance(IMPORT_HEROIC, str):
        IMPORT_HEROIC = IMPORT_HEROIC == "1"
    if not IMPORT_HEROIC:
        log("Heroic import disabled.")
        report["status"] = "disabled"
        return []

    include_sources = [s.strip() for s in str(settings.get("INCLUDE_SOURCES", "epic,gog,amazon")).lower().split(",") if s.strip()]
    blacklist_name_regex = str(settings.get("BLACKLIST_NAME_REGEX", ""))

    # Ensure target image dirs exist. Also keep a sibling "sideload" dir like the monolith.
    os.makedirs(images_dir, exist_ok=True)
    images_dir_sideload = os.path.join(os.path.dirname(images_dir), "sideload")
    os.makedirs(images_dir_sideload, exist_ok=True)

    # Heroic config root detection (Flatpak first, then native)
    if os.name == "nt":
        # Windows keeps it in %APPDATA%, not a dotted directory under $HOME.
        # Without this the importer found nothing at all on a machine with
        # Heroic installed and games in it -- measured on the rig.
        appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        fallbacks = [os.path.join(appdata, "heroic")]
    else:
        fallbacks = [
            f"{home}/.var/app/com.heroicgameslauncher.hgl/config/heroic",
            f"{home}/.config/heroic",
        ]
    hero_conf_root = next((p for p in fallbacks if os.path.isdir(p)), "")
    if not hero_conf_root:
        log("Heroic config root not found; skipping Heroic import.")
        return []
    report["status"] = "ok"
    report["root"] = hero_conf_root

    # Launch prefix and mode
    if "/.var/app/" in hero_conf_root:
        heroic_kind = "flatpak"
        heroic_prefix = "flatpak run com.heroicgameslauncher.hgl "
        add_silent_param = True   # matches the monolith behavior
    elif os.name == "nt":
        # No prefix: Windows resolves a heroic:// URL through the scheme handler
        # Heroic registers, which is how Sunshine runs it too. xdg-open does not
        # exist here, and prefixing anything would make the whole string a
        # command Windows cannot find.
        heroic_kind = "native"
        heroic_prefix = ""
        add_silent_param = False
    else:
        heroic_kind = "native"
        heroic_prefix = "xdg-open "
        add_silent_param = False

    log(f"Heroic: {heroic_kind} | conf: {hero_conf_root}")

    legendary_installed = os.path.join(hero_conf_root, "legendaryConfig", "legendary", "installed.json")
    gog_installed       = os.path.join(hero_conf_root, "gog_store", "installed.json")
    amazon_candidates   = [
        os.path.join(hero_conf_root, "nile_library", "library.json"),
        os.path.join(hero_conf_root, "nile_library", "installed.json"),
        os.path.join(hero_conf_root, "nile_store", "installed.json"),
        os.path.join(hero_conf_root, "amazon_store", "installed.json"),
        os.path.join(hero_conf_root, "nile", "installed.json"),
    ]
    games_cfg_dir       = os.path.join(hero_conf_root, "GamesConfig")
    sideload_library    = os.path.join(hero_conf_root, "sideload_apps", "library.json")

    # ---------------------- Cache variables (module-level within function scope) ----------------------
    # These need to be declared before the helper functions that use them
    _title_cache: Dict[str, str] = {}
    _image_url_cache: Dict[str, str] = {}
    _caches_built = False
    _cache_build_lock = threading.Lock()

    # ---------------------- helpers for Heroic/GOG ----------------------
    INVALID_TITLES = {
        "heroic", "default", "title", "unknown", "game", "gog"
    }

    def is_valid_game_title(v: str) -> bool:
        if not isinstance(v, str):
            return False
        s = v.strip()
        if not s:
            return False
        sl = s.lower()
        if sl in INVALID_TITLES:
            return False
        # Reject pure numeric ids and "gog <id>" placeholders.
        if s.isdigit():
            return False
        if re.fullmatch(r"gog\s+\d+", sl):
            return False
        return True

    def first_non_empty(*vals) -> str:
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def first_valid_title(*vals) -> str:
        for v in vals:
            if is_valid_game_title(v):
                return v.strip()
        return ""

    def load_json_if(path):
        try:
            if os.path.isfile(path):
                return read_json(path, {})
        except Exception as e:
            log(f"Warn: failed loading JSON {path}: {e}")
        return {}

    def humanize_slug(s: str) -> str:
        s = re.sub(r"[_\-]+", " ", s or "")
        s = re.sub(r"\s+", " ", s).strip()
        return s.title()

    def _as_bool(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            sv = v.strip().lower()
            if sv in ("1", "true", "yes", "on"):
                return True
            if sv in ("0", "false", "no", "off"):
                return False
        return None

    def _existing_path(p: str) -> str:
        p = str(p or "").strip()
        if not p:
            return ""
        ep = os.path.expandvars(os.path.expanduser(p))
        return ep if os.path.exists(ep) else ""

    def scan_gamescfg_for_title(gid: str, install_path: str) -> str:
        if not os.path.isdir(games_cfg_dir):
            return ""
        try:
            for cfg_path in glob.glob(os.path.join(games_cfg_dir, "*.json")):
                cfg = load_json_if(cfg_path)
                if not isinstance(cfg, dict):
                    continue
                appname = str(cfg.get("appName") or cfg.get("app_name") or cfg.get("id") or "")
                ipath   = str(cfg.get("installPath") or cfg.get("install_path") or "")
                # match by id or install path
                if (gid and appname == str(gid)) or (install_path and ipath and os.path.normpath(ipath) == os.path.normpath(install_path)):
                    t = first_valid_title(
                        cfg.get("title"),
                        cfg.get("appTitle"),
                        cfg.get("gameTitle"),
                        (cfg.get("productInfo") or {}).get("title") if isinstance(cfg.get("productInfo"), dict) else ""
                    )
                    if t:
                        return t
        except Exception as e:
            log(f"Warn: scan GamesConfig failed: {e}")
        return ""

    # _ID_KEYS used to match appName/id fields in any JSON object
    _TITLE_ID_KEYS = {"appName", "app_name", "appname", "app_id", "appId", "id", "productId", "productID"}
    _TITLE_FIELDS  = ("title", "appTitle", "gameTitle", "name", "displayName")

    # Build global caches by scanning all JSONs once (memoized)
    _title_cache: Dict[str, str] = {}
    _image_url_cache: Dict[str, str] = {}
    _caches_built = False
    
    def _build_caches() -> tuple[Dict[str, str], Dict[str, str]]:
        """
        One-time scan of all JSON files to build both gid->title and gid->image_url mappings.
        Much faster than separate scans for each cache.
        """
        nonlocal _caches_built, _title_cache, _image_url_cache
        if _caches_built:
            return _title_cache, _image_url_cache

        with _cache_build_lock:
            if _caches_built:
                return _title_cache, _image_url_cache
        
            app_root = Path(hero_conf_root).parent.parent
            if not app_root.is_dir():
                app_root = Path(hero_conf_root)

            log(f"Building Heroic metadata cache from {app_root}...")
            title_cache: Dict[str, str] = {}
            image_cache: Dict[str, str] = {}
            scanned = 0

            # This is the longest thing a scan does -- fourteen thousand files
            # and the best part of a minute on a real library -- and it used to
            # say nothing between its first line and its last. The interface
            # shows the most recent line, so a line that moves is the
            # difference between a scan and a hung program.
            next_note = time.monotonic() + PROGRESS_EVERY

            for jf in app_root.rglob("*.json"):
                try:
                    data = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
                    scanned += 1
                except Exception:
                    continue

                now = time.monotonic()
                if now >= next_note:
                    next_note = now + PROGRESS_EVERY
                    log(f"Reading Heroic's library: {scanned} files so far...")

                # Single pass: extract both titles and image URLs
                for _, node in _walk_json(data):
                    if not isinstance(node, dict):
                        continue

                    # Extract all possible IDs from this node
                    gids = set()
                    for k in _TITLE_ID_KEYS:
                        if k in node:
                            val = str(node.get(k) or "")
                            if val:
                                gids.add(val)

                    if not gids:
                        continue

                    # Extract best title from this node
                    title = first_valid_title(*(node.get(f) for f in _TITLE_FIELDS))

                    # Extract best image URL from this node
                    urls = _extract_urls_from_node(node)
                    best_url = ""
                    if urls:
                        urls.sort(key=lambda t: (t[1], t[2], t[3], t[4], t[5], -len(t[0])), reverse=True)
                        best_url = urls[0][0] if urls else ""

                    # Store for all IDs found in this node (keep first match)
                    for gid in gids:
                        if title and gid not in title_cache:
                            title_cache[gid] = title
                        if best_url and gid not in image_cache:
                            image_cache[gid] = best_url

            log(f"Heroic cache built from {scanned} files: {len(title_cache)} titles, {len(image_cache)} images")
            _title_cache.update(title_cache)
            _image_url_cache.update(image_cache)
            _caches_built = True
            return _title_cache, _image_url_cache

    def _scan_all_jsons_for_title(gid: str) -> str:
        """
        Look up title from the pre-built cache.
        """
        title_cache, _ = _build_caches()
        return title_cache.get(gid, "")

    def resolve_gog_title(it: dict, gid: str, install_path: str, hero_conf_root: str) -> str:
        # 1) direct fields from installed.json entry
        t = first_valid_title(it.get("title"), it.get("gameTitle"), it.get("appTitle"))
        if t:
            return t

        # nested game blob
        g = it.get("game") if isinstance(it.get("game"), dict) else {}
        t = first_valid_title(g.get("title"), g.get("name"))
        if t:
            return t

        # 2) GamesConfig/<gid>.json exact
        cfg_exact = os.path.join(games_cfg_dir, f"{gid}.json")
        cfg = load_json_if(cfg_exact)
        if cfg:
            # GamesConfig files can be flat OR nested under the gid key: { "<gid>": { ... } }
            cfg_game = cfg.get(str(gid)) if isinstance(cfg.get(str(gid)), dict) else cfg
            t = first_valid_title(
                cfg_game.get("title"), cfg_game.get("appTitle"), cfg_game.get("gameTitle"),
                (cfg_game.get("productInfo") or {}).get("title") if isinstance(cfg_game.get("productInfo"), dict) else ""
            )
            if t:
                return t

        # 3) Scan GamesConfig/*.json by id or installPath
        t = scan_gamescfg_for_title(gid, install_path)
        if t:
            return t

        # 4) Broad scan — all JSON files under the Heroic app data root
        t = _scan_all_jsons_for_title(gid)
        if t:
            return t

        # 5) Install folder name → title (only if not a generic placeholder)
        if install_path:
            folder = os.path.basename(os.path.normpath(install_path))
            if is_valid_game_title(folder):
                return humanize_slug(folder)

        # 6) slug → human
        slug = first_non_empty(it.get("slug"), it.get("appName"), it.get("app_name"))
        if slug and not str(slug).isdigit():
            return humanize_slug(str(slug))

        return f"GOG {gid}"

    def resolve_amazon_title(it: dict, gid: str, install_path: str) -> str:
        t = first_valid_title(
            it.get("title"), it.get("appTitle"), it.get("gameTitle"),
            it.get("name"), it.get("displayName"), it.get("productName")
        )
        if t:
            return t

        game = it.get("game") if isinstance(it.get("game"), dict) else {}
        product = it.get("productInfo") if isinstance(it.get("productInfo"), dict) else {}
        t = first_valid_title(
            game.get("title"), game.get("name"),
            product.get("title"), product.get("name")
        )
        if t:
            return t

        t = _scan_all_jsons_for_title(gid)
        if t:
            return t

        if install_path:
            folder = os.path.basename(os.path.normpath(install_path))
            if is_valid_game_title(folder):
                return humanize_slug(folder)

        slug = first_non_empty(
            it.get("slug"), it.get("appName"), it.get("app_name"),
            it.get("id"), it.get("asin")
        )
        if slug and not str(slug).isdigit():
            return humanize_slug(str(slug))

        return f"Amazon {gid}"

    def parse_installed_items(raw: Any) -> List[dict]:
        items: List[dict] = []
        if isinstance(raw, dict) and isinstance(raw.get("installed"), list):
            items = raw.get("installed", [])
        elif isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            for key in ("games", "apps", "library", "entries"):
                val = raw.get(key)
                if isinstance(val, list):
                    items = val
                    break
                if isinstance(val, dict):
                    items = []
                    for k, v in val.items():
                        if isinstance(v, dict):
                            it = dict(v)
                            it.setdefault("id", str(k))
                            items.append(it)
                    if items:
                        break

            if not items:
                for k, v in raw.items():
                    if not isinstance(v, dict):
                        continue
                    it = dict(v)
                    it.setdefault("id", str(k))
                    items.append(it)

        out: List[dict] = []
        for it in items:
            if isinstance(it, dict):
                out.append(it)
        return out

    # ====== Heroic cached image resolver (for Epic/GOG) ======
    _JSON_URL_RX = re.compile(r"https?://[^\s\"'<>]+", re.I)

    # Keys that can contain the *exact* game id
    _ID_KEYS = {
        "appName","app_name","appname","app-id","appId","app_id",
        "productId","productID","product_id","id","gameId","game_id",
        "titleId","title_id","catalogItemId","catalog_item_id","slug","productSlug"
    }

    # Epic image "type" preferences seen in catalog / assets
    _EPIC_TYPE_PREFER = (
        "DieselGameBoxTall","VaultBoxArtTall","OfferImageTall","DieselGameBox",
        "ProductPromoArt","KeyArt","ComingSoonBoxArt","StoreTall"
    )

    # Prefer “cover-ish”, de-prioritize non-cover art across both platforms
    _URL_PREFER = ("cover","boxart","poster","portrait","front","artwork","keyart","hero","tall","vertical")
    _URL_DEPRIO = ("screenshot","logo","icon","background","wallpaper","banner","landscape","wide","placeholder","default")

    # Keys frequently carrying cover-ish URLs in GOG/Epic JSONs
    _COVER_KEYS = {
        "art_cover","cover","coverUrl","coverURL","gridCover","verticalCover","portrait","vertical",
        "imageUrl","imageURL","heroImage","hero_image","boxArt","poster","tile","thumb","grid","banner","logo_square"
    }

    def _walk_json(node, path=()):
        yield path, node
        if isinstance(node, dict):
            for k, v in node.items():
                yield from _walk_json(v, path+(k,))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from _walk_json(v, path+(i,))

    def _node_has_exact_gid(node, gid: str) -> bool:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _ID_KEYS and str(v) == gid:
                    return True
        return False

    def _node_mentions_gid(node, gid: str) -> bool:
        for _, v in _walk_json(node):
            if isinstance(v, str) and gid in v:
                return True
            if not isinstance(v, (dict, list)) and str(v) == gid:
                return True
        return False

    def _extract_urls_from_node(node) -> list[tuple[str,int,int,int,int]]:
        """
        Return list of tuples: (url, epic_type_rank, cover_key_hit, has_img_ext, prefer_score, -deprio_score)
        so we can sort deterministically.
        """
        out: list[tuple[str,int,int,int,int]] = []

        def push(u: str, epic_type_rank: int = 0, cover_key_hit: int = 0):
            us = u.lower()
            has_ext = int(any(us.split("?",1)[0].endswith(ext) for ext in (".png",".jpg",".jpeg",".webp",".avif")))
            prefer = sum(1 for s in _URL_PREFER if s in us)
            deprio = sum(1 for s in _URL_DEPRIO if s in us)
            # discard obvious placeholders early
            if "placeholder" in us or "default" in us:
                return
            out.append((u, epic_type_rank, cover_key_hit, has_ext, prefer, -deprio))

        # 1) Dedicated cover-ish fields (dictionary keys)
        if isinstance(node, dict):
            for k in list(node.keys()):
                if k in _COVER_KEYS:
                    val = node.get(k)
                    if isinstance(val, str) and _JSON_URL_RX.match(val):
                        push(val, cover_key_hit=1)

        # 2) Epic-style image arrays: [{"type":"DieselGameBoxTall","url": "..."}]
        def grab_from_img_obj(obj):
            if not isinstance(obj, dict):
                return
            url = obj.get("url") or obj.get("src") or obj.get("image") or obj.get("ImageUrl") or obj.get("imageUrl")
            if isinstance(url, str) and _JSON_URL_RX.match(url):
                t = str(obj.get("type",""))
                epic_rank = 2 if t in _EPIC_TYPE_PREFER else (1 if ("Tall" in t or "Vertical" in t or "BoxArt" in t) else 0)
                push(url, epic_type_rank=epic_rank)

        if isinstance(node, dict):
            for key in ("images","image","media","assets","imageList","imagesList","keyImages"):
                val = node.get(key)
                if isinstance(val, list):
                    for item in val:
                        grab_from_img_obj(item)
                elif isinstance(val, dict):
                    for item in val.values():
                        grab_from_img_obj(item)

        # 3) Any URL-looking string anywhere in the node (last resort)
        for _, v in _walk_json(node):
            if isinstance(v, str):
                for m in _JSON_URL_RX.findall(v):
                    push(m)

        return out

    def heroic_find_image_url_for_gid(hero_conf_root: str, gid: str) -> str:
        """
        Look up image URL from the pre-built cache.
        """
        _, image_cache = _build_caches()
        return image_cache.get(gid, "")

    def heroic_cover_png_from_json(hero_conf_root: str, gid: str, images_dir: str) -> str:
        """
        JSON-only discovery to get a cover URL (strict gid-anchored), download, stretch 600x900 PNG.
        """
        url = heroic_find_image_url_for_gid(hero_conf_root, gid)
        if not url:
            return ""
        tmp = download_temp(url)
        if not tmp:
            return ""
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"heroic_{gid}").strip("_") or f"heroic_{gid}"
        dst = os.path.join(images_dir, f"{safe}.png")
        ok = stretch_png_600x900(tmp, dst)
        try:
            os.remove(tmp)
        except Exception:
            pass
        return dst if ok and os.path.isfile(dst) else ""

    heroic_apps: List[Dict[str, Any]] = []
    
    # Store games needing image downloads
    games_needing_images: List[Dict[str, Any]] = []

    def add_heroic(title, gid, install_path, src, image_path="", source_json=""):
        # Name blacklist by regex
        if blacklist_name_regex:
            for pat in blacklist_name_regex.split("|"):
                if pat and re.search(pat, str(title or ""), re.I):
                    log(f"Skip {src} {title} ({gid}) [blacklist]")
                    return

        runner_map = {
            "Sideload": "sideload",
            "Amazon": "nile",
        }
        runner = runner_map.get(src, src.lower())
        base = f"heroic://launch?appName={gid}&runner={runner}"
        if add_silent_param:
            base += "&silent=true"

        cmd = f"{heroic_prefix}{base}"
        
        # Store game metadata - images will be downloaded later in batch
        game_entry = {
            "name": f"{title or gid} ({src})",
            "output": "",
            "cmd": cmd,
            "working-dir": install_path or home,
            "image-path": image_path or "",  # May be pre-set (sideload)
            "detached": False,
            "elevated": False,
            "exit-on-close": True,
            "_gid": gid,
            "_title": title,
            "_src": src,
        }
        
        # If no image path provided, mark for concurrent download
        if not image_path:
            games_needing_images.append(game_entry)
        
        heroic_apps.append(game_entry)
        log(f"Found {src}  {yn(title or gid)}")

    # --------------------- EPIC (Legendary) ---------------------
    if "epic" in include_sources:
        if os.path.isfile(legendary_installed):
            try:
                raw = read_json(legendary_installed, {})
                for gid, val in (raw or {}).items():
                    install_path = str((val or {}).get("install_path") or "")
                    title = (val or {}).get("title") or (val or {}).get("app_title") or gid
                    add_heroic(title, gid, install_path, "Epic")
            except Exception as e:
                log(f"Failed to parse Epic installed.json: {e}")

    # --------------------- GOG ---------------------
    # Get installed game IDs from gog_store/installed.json, then use GamesConfig for names
    if "gog" in include_sources:
        # First, get list of installed game IDs
        installed_gog = {}
        if os.path.isfile(gog_installed):
            data = read_json(gog_installed, {})
            if isinstance(data, dict) and isinstance(data.get("installed"), list):
                items = data.get("installed", [])
            elif isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                # Some Heroic versions store installed.json as a map: { "<gid>": { ... } }
                items = []
                for k, v in data.items():
                    if not isinstance(v, dict):
                        continue
                    it = dict(v)
                    it.setdefault("id", str(k))
                    items.append(it)
            else:
                items = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                gid = it.get("appName") or it.get("app_name") or it.get("id")
                if gid:
                    installed_gog[str(gid)] = it
        
        if installed_gog and os.path.isdir(games_cfg_dir):
            # Now iterate GamesConfig and process only installed games
            seen_gog_ids = set()
            for cfg_path in glob.glob(os.path.join(games_cfg_dir, "*.json")):
                cfg = load_json_if(cfg_path)
                if not isinstance(cfg, dict):
                    continue
                
                # Get all keys except "version" and "explicit"
                game_ids = [k for k in cfg.keys() if k not in ("version", "explicit")]
                
                for gid in game_ids:
                    if not gid or gid in seen_gog_ids:
                        continue
                    # Only process if this game is actually installed
                    if gid not in installed_gog:
                        continue

                    game_data = cfg.get(gid)
                    if not isinstance(game_data, dict):
                        continue

                    seen_gog_ids.add(gid)
                    
                    # Get winePrefix and extract basename as game name
                    prefix = game_data.get("winePrefix", "")
                    if prefix:
                        gname = os.path.basename(os.path.normpath(prefix))
                        if is_valid_game_title(gname) and gname not in ("", "/", "."):
                            title = gname
                        else:
                            title = gid
                    else:
                        title = gid
                    
                    # Resolve a working dir from installed metadata first; if path does not exist
                    # on this machine, still keep the entry since installed.json is authoritative.
                    installed_meta = installed_gog.get(gid, {})
                    raw_install_path = (
                        str(installed_meta.get("installPath") or installed_meta.get("install_path") or "")
                        or game_data.get("installPath", "")
                        or game_data.get("install_path", "")
                    )
                    install_path = str(raw_install_path or "")

                    # If GamesConfig gave a generic title (default/title/heroic), resolve from metadata/id.
                    if not is_valid_game_title(title):
                        resolved = resolve_gog_title(installed_meta if isinstance(installed_meta, dict) else {}, str(gid), install_path, hero_conf_root)
                        title = resolved if is_valid_game_title(resolved) else humanize_slug(str(gid))
                    
                    add_heroic(title, gid, install_path, "GOG", source_json=cfg_path)

            # Fallback: some installed GOG IDs may not exist in GamesConfig yet.
            for gid, it in installed_gog.items():
                if gid in seen_gog_ids:
                    continue
                if not isinstance(it, dict):
                    continue
                install_path = str(it.get("installPath") or it.get("install_path") or "")
                title = resolve_gog_title(it, str(gid), install_path, hero_conf_root)
                if not is_valid_game_title(title):
                    title = humanize_slug(str(gid))
                add_heroic(title, str(gid), install_path, "GOG", source_json=gog_installed)
        elif installed_gog:
            # Fallback: import from installed.json when GamesConfig is unavailable.
            for gid, it in installed_gog.items():
                if not isinstance(it, dict):
                    continue
                install_path = str(it.get("installPath") or it.get("install_path") or "")
                title = resolve_gog_title(it, str(gid), install_path, hero_conf_root)
                if not is_valid_game_title(title):
                    title = humanize_slug(str(gid))
                add_heroic(title, str(gid), install_path, "GOG", source_json=gog_installed)

    # --------------------- AMAZON (Nile) ---------------------
    if "amazon" in include_sources:
        installed_amazon: Dict[str, dict] = {}
        seen_source = ""

        for amazon_path in amazon_candidates:
            if not os.path.isfile(amazon_path):
                continue
            seen_source = seen_source or amazon_path
            data = read_json(amazon_path, {})
            for it in parse_installed_items(data):
                gid = first_non_empty(
                    it.get("appName"), it.get("app_name"), it.get("productId"),
                    it.get("asin"), it.get("id"), it.get("slug")
                )
                if not gid:
                    continue

                installed_flag = None
                for k in ("is_installed", "isInstalled", "installed"):
                    if k in it:
                        installed_flag = _as_bool(it.get(k))
                        break
                if installed_flag is False:
                    continue

                installed_amazon[str(gid)] = it

        for gid, it in installed_amazon.items():
            install_path = first_non_empty(
                it.get("installPath"), it.get("install_path"),
                it.get("path"), it.get("gamePath"), it.get("location")
            )
            title = resolve_amazon_title(it, str(gid), install_path)
            if not is_valid_game_title(title):
                title = humanize_slug(str(gid))
            add_heroic(title, str(gid), install_path, "Amazon", source_json=seen_source)

        # Fallback: try to detect Amazon entries from GamesConfig when nile_* json files are missing.
        if not installed_amazon and os.path.isdir(games_cfg_dir):
            for cfg_path in glob.glob(os.path.join(games_cfg_dir, "*.json")):
                cfg = load_json_if(cfg_path)
                if not isinstance(cfg, dict):
                    continue

                for k, v in cfg.items():
                    if k in ("version", "explicit") or not isinstance(v, dict):
                        continue

                    runner_hint = " ".join(
                        str(v.get(x) or "") for x in ("runner", "store", "source", "platform", "backend")
                    ).lower()
                    if "amazon" not in runner_hint and "nile" not in runner_hint:
                        continue

                    gid = first_non_empty(v.get("appName"), v.get("app_name"), v.get("id"), k)
                    if not gid:
                        continue

                    title = first_valid_title(v.get("title"), v.get("name"), v.get("displayName"))
                    install_path = first_non_empty(v.get("installPath"), v.get("install_path"))

                    if not is_valid_game_title(title):
                        title = resolve_amazon_title(v, str(gid), install_path)
                    if not is_valid_game_title(title):
                        title = humanize_slug(str(gid))

                    add_heroic(title, str(gid), install_path, "Amazon", source_json=cfg_path)

    # --------------------- SIDELOAD ---------------------
    if os.path.isfile(sideload_library):
        try:
            raw = read_json(sideload_library, {})
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, dict):
                for key in ("apps", "library", "entries", "games"):
                    if key in raw and isinstance(raw[key], list):
                        items = raw[key]
                        break
                else:
                    items = list(raw.values())
            else:
                items = []

            count = 0
            for it in items:
                if not isinstance(it, dict):
                    continue
                sid = it.get("appName") or it.get("app_name") or it.get("slug") or it.get("id")
                title = it.get("title") or it.get("name") or it.get("displayName") or sid
                exe   = it.get("executable") or it.get("exe") or it.get("bin") or ""
                workd = it.get("workingDir") or it.get("workDir") or (os.path.dirname(exe) if exe else home)

                # Ensure sideload entries are actually installed.
                installed_flag = None
                for k in ("is_installed", "isInstalled", "installed"):
                    if k in it:
                        installed_flag = _as_bool(it.get(k))
                        break
                exe_path = _existing_path(exe)
                workd_path = _existing_path(workd)
                if installed_flag is False:
                    continue
                if not exe_path and not workd_path:
                    continue

                cover_url = it.get("art_cover") or it.get("imageUrl") or it.get("imagePath") or ""
                out_cover = ""
                if cover_url:
                    tmp_src = download_temp(cover_url)
                    if tmp_src:
                        base = slugify(sid or title or "sideload")
                        dst = os.path.join(images_dir_sideload, f"{base}.png")
                        if stretch_png_600x900(tmp_src, dst):
                            out_cover = dst
                        else:
                            try:
                                # fallback direct copy
                                import shutil as _sh
                                _sh.copy2(tmp_src, dst)
                                out_cover = dst
                            except Exception:
                                out_cover = ""
                        try:
                            os.remove(tmp_src)
                        except Exception:
                            pass
                add_heroic(title or sid, sid, workd_path or os.path.dirname(exe_path) or workd or home, "Sideload", image_path=out_cover)
                count += 1
            log(f"Sideload parsed: {count} entries")
        except Exception as e:
            log(f"Failed to parse sideload library: {e}")
    else:
        log(f"No sideload library.json at {sideload_library}")

    # Download all missing images concurrently
    if games_needing_images:
        api_key = str(settings.get("SGDB_API_KEY", ""))
        sgdb_enable = bool(int(settings.get("SGDB_ENABLE", 1)))
        timeout = int(settings.get("SGDB_TIMEOUT", 6))  # Reduced default timeout
        
        downloader = ImageDownloader(max_workers=10)
        download_tasks = {}
        
        for game in games_needing_images:
            gid = game["_gid"]
            title = game["_title"]
            src = game["_src"]
            
            # Create download function for this game
            def make_download_func(g_id, g_title, g_src):
                def download():
                    # Try JSON-only discovery first (Epic/GOG)
                    if g_src in ("Epic", "GOG", "Amazon"):
                        try:
                            png = heroic_cover_png_from_json(hero_conf_root, str(g_id), images_dir)
                            if png:
                                return png
                        except Exception:
                            pass
                    
                    # Fallback to SteamGridDB
                    if api_key and sgdb_enable:
                        try:
                            search_name = g_title or g_id
                            safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", f"heroic_{g_id}").strip("_") or f"heroic_{g_id}"
                            sgdb_png = sgdb_search_by_name(search_name, images_dir, safe_filename, api_key, sgdb_enable, timeout)
                            if sgdb_png:
                                return sgdb_png
                        except Exception:
                            pass
                    return None
                return download
            
            download_tasks[str(gid)] = make_download_func(gid, title, src)
        
        # Download all images concurrently
        image_results = downloader.download_batch(download_tasks, desc="Heroic")
        
        # Update apps with downloaded images
        for game in games_needing_images:
            gid = game["_gid"]
            image_path = image_results.get(str(gid), "")
            if image_path:
                game["image-path"] = image_path
    
    # Replace the scratch fields with an ownership marker
    tagged: List[Dict[str, Any]] = []
    for app in heroic_apps:
        gid = app.pop("_gid", "")
        src = app.pop("_src", "heroic")
        app.pop("_title", None)
        tagged.append(tag(app, str(src).lower(), gid))

    return tagged
