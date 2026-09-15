# SPDX-License-Identifier: GPL-3.0-or-later
"""
Concurrent image downloader for Sunshine app covers.
Significantly speeds up image fetching by downloading in parallel.
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Callable, Optional, Any
from .utils import log


class ImageDownloader:
    """Manages concurrent image downloads with progress tracking."""
    
    def __init__(self, max_workers: int = 10):
        """
        Args:
            max_workers: Maximum number of concurrent download threads
        """
        self.max_workers = max_workers
        self._results: Dict[str, Optional[str]] = {}
    
    def download_batch(
        self, 
        tasks: Dict[str, Callable[[], Optional[str]]], 
        desc: str = "images"
    ) -> Dict[str, Optional[str]]:
        """
        Download multiple images concurrently.
        
        Args:
            tasks: Dict mapping task_id -> download_function
                   Each function should return the path to downloaded image or None
            desc: Description for logging (e.g., "Steam", "Heroic")
            
        Returns:
            Dict mapping task_id -> image_path (or None if failed)
        """
        if not tasks:
            return {}
        
        results: Dict[str, Optional[str]] = {}
        total = len(tasks)
        completed_count = 0
        
        log(f"Downloading {total} {desc} covers concurrently (max {self.max_workers} workers)...")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_id = {
                executor.submit(func): task_id 
                for task_id, func in tasks.items()
            }
            
            # Process as they complete
            for future in as_completed(future_to_id):
                task_id = future_to_id[future]
                try:
                    result = future.result()
                    results[task_id] = result
                    completed_count += 1
                    if completed_count % 10 == 0 or completed_count == total:
                        log(f"  Downloaded {completed_count}/{total} {desc} images...")
                except Exception as e:
                    log(f"  Error downloading {task_id}: {e}")
                    results[task_id] = None
        
        successful = sum(1 for v in results.values() if v)
        log(f"Completed {desc} downloads: {successful}/{total} successful")
        return results


def download_image_if_missing(
    image_path: str,
    download_func: Callable[[], Optional[str]]
) -> Optional[str]:
    """
    Helper to download image only if it doesn't exist or is invalid.
    
    Args:
        image_path: Expected path for the image
        download_func: Function to call to download the image
        
    Returns:
        Path to image if successful, None otherwise
    """
    # Quick check: if file exists and has reasonable size, assume it's valid
    if os.path.isfile(image_path):
        try:
            size = os.path.getsize(image_path)
            if size > 1000:  # Minimum reasonable size
                return image_path
        except Exception:
            pass
    
    # Download
    return download_func()
