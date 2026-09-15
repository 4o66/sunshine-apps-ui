# SPDX-License-Identifier: GPL-3.0-or-later
import os, re, glob, json, pathlib
from typing import List, Dict, Any
from ..utils import log, yn, read_json
from ..images import steam_local_to_png, steam_cdn_to_png, steam_sgdb_to_png
from ..image_downloader import ImageDownloader
from ..reconcile import tag
from ..artwork_sources import find_steam_root

def import_steam(home: str, conf_dir: str, images_dir: str, settings: Dict[str, Any],
                 report: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    # `report`, when given, is filled with how the scan went. "ok" means the
    # library was found and read; anything else means its absence proves nothing
    # about whether the user still has these games installed.
    if report is None:
        report = {}
    report["status"] = "not_found"

    IMPORT_STEAM = settings.get("IMPORT_STEAM", True)
    if not IMPORT_STEAM:
        log("Steam import disabled."); report["status"] = "disabled"; return []

    # Shared with the artwork picker, which needs the same root to offer the
    # library cache Steam has already filled in.
    steam_root, steam_mode = find_steam_root(home)

    if not steam_root or not os.path.isdir(os.path.join(steam_root, "steamapps")):
        log("Steam not found; skipping Steam import."); return []
    report["status"] = "ok"
    report["root"] = steam_root

    log(f"Steam: {steam_mode} at {steam_root}")

    # library dirs
    lib_dirs = []
    lib_vdf = os.path.join(steam_root,"steamapps","libraryfolders.vdf")
    if os.path.isfile(lib_vdf):
        for line in open(lib_vdf,"r",encoding="utf-8",errors="ignore"):
            m = re.search(r'"path"\s*"([^"]+)"', line)
            if m:
                p = os.path.join(m.group(1),"steamapps")
                if os.path.isdir(p): lib_dirs.append(p)
    lib_dirs.append(os.path.join(steam_root,"steamapps"))
    # Deduplicate by resolved path, not by string. On ostree systems (Bazzite,
    # Silverblue) /home is a symlink to /var/home, so libraryfolders.vdf can name
    # the same directory as steam_root by a different path and every game in it
    # gets imported twice. Keep the first spelling seen.
    seen=set(); deduped=[]
    for d in lib_dirs:
        key = os.path.realpath(d)
        if key in seen: continue
        seen.add(key); deduped.append(d)
    lib_dirs = deduped

    # blacklist
    bl_ids=set(); bl_patterns=[]
    if settings.get("USE_DEFAULT_BLACKLIST", True):
        bl_patterns += [
            r"Steamworks Common Redistributables", r"Proton",
            r"SteamVR|OpenVR|Valve Index", r"Soundtrack",
            r"Dedicated Server|Server", r"SDK|Editor|Mod Tools|Tools?",
            r"Demo", r"Benchmark|Test",
            r"Runtime", r"Workshop", r"Big Picture", r"Source",
            r"Linux Runtime", r"Redistributables", r"Desktop Mode",
        ]
    if str(settings.get("BLACKLIST_IDS","")).strip():
        for tok in re.split(r"[,\s]+", str(settings.get("BLACKLIST_IDS")).strip()):
            if tok.isdigit(): bl_ids.add(int(tok))
    bl_path = settings.get("BLACKLIST_FILE") or os.path.join(conf_dir,"steam-import.blacklist")
    if os.path.isfile(bl_path):
        for line in open(bl_path,"r",encoding="utf-8",errors="ignore"):
            line=line.split("#",1)[0].strip()
            if not line: continue
            if line.isdigit(): bl_ids.add(int(line))
            else: bl_patterns.append(line)
    if str(settings.get("BLACKLIST_NAME_REGEX","")).strip():
        bl_patterns += [p for p in str(settings.get("BLACKLIST_NAME_REGEX")).split("|") if p]

    def blacklisted(appid, name):
        if appid in bl_ids: return True
        for pat in bl_patterns:
            try:
                if re.search(pat, name, re.I): return True
            except re.error:
                if pat.lower() in name.lower(): return True
        return False

    # First pass: collect all game metadata without downloading images
    game_metadata = []
    app_count = 0
    for sd in lib_dirs:
        for path in glob.glob(os.path.join(sd,"appmanifest_*.acf")):
            try: txt=open(path,"r",encoding="utf-8",errors="ignore").read()
            except Exception: continue
            m_id=re.search(r'"appid"\s*"(\d+)"',txt)
            m_name=re.search(r'"name"\s*"([^"]+)"',txt)
            m_dir=re.search(r'"installdir"\s*"([^"]+)"',txt)
            if not (m_id and m_name): continue
            appid=int(m_id.group(1)); name=m_name.group(1); app_count+=1
            install_dir = m_dir.group(1).strip() if m_dir else ""
            install_path = os.path.join(sd, "common", install_dir) if install_dir else ""
            if not install_path or not os.path.isdir(install_path):
                log(f"Skipping non-installed Steam [{appid}] {name}")
                continue
            if blacklisted(appid, name):
                log(f"Skipping blacklisted [{appid}] {name}")
                continue

            if steam_mode=="flatpak":
                cmd=f'flatpak-spawn --host flatpak run com.valvesoftware.Steam steam -applaunch {appid}'
                workdir=f"{home}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
            else:
                cmd=f'steam -applaunch {appid}'
                workdir=steam_root
            
            game_metadata.append({
                "appid": appid,
                "name": name,
                "cmd": cmd,
                "workdir": workdir
            })
            log(f"Found Steam  [{appid}] {yn(name)}")
    
    log(f"Steam installed scanned: {app_count}")
    report["scanned"] = app_count
    report["libraries"] = list(lib_dirs)
    
    # Second pass: download all images concurrently
    timeout = int(settings.get("SGDB_TIMEOUT", 6))  # Reduced default timeout
    api_key = str(settings.get("SGDB_API_KEY", ""))
    sgdb_enable = bool(int(settings.get("SGDB_ENABLE", 1)))
    
    downloader = ImageDownloader(max_workers=10)
    download_tasks = {}
    
    for game in game_metadata:
        appid = game["appid"]
        # Create download function for this game
        def make_download_func(aid):
            def download():
                return (steam_local_to_png(aid, images_dir, steam_root=steam_root) or
                        steam_cdn_to_png(aid, images_dir, timeout=timeout) or
                        steam_sgdb_to_png(aid, images_dir, api_key=api_key,
                                        enable=sgdb_enable, timeout=timeout))
            return download
        download_tasks[str(appid)] = make_download_func(appid)
    
    # Download all images concurrently
    image_results = downloader.download_batch(download_tasks, desc="Steam")
    
    # Third pass: assemble final app entries with downloaded images
    apps = []
    for game in game_metadata:
        appid = game["appid"]
        image_path = image_results.get(str(appid), "")
        apps.append(tag({
            "name": game["name"], 
            "output": "", 
            "cmd": game["cmd"], 
            "working-dir": game["workdir"],
            "image-path": image_path or "", 
            "detached": False, 
            "elevated": False, 
            "exit-on-close": True
        }, "steam", appid))
    
    return apps
