import requests
from PIL import Image, ImageDraw, ImageOps
import io
import math
import random
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import multiprocessing
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import mimetypes

# Load environment variables
load_dotenv()

class S3Storage:
    """Generic S3-compatible storage class (works with AWS S3, Cloudflare R2, etc.)"""
    
    def __init__(self):
        self.enabled = os.getenv('S3_ENABLED', 'false').lower() == 'true'
        
        if self.enabled:
            self.endpoint_url = os.getenv('S3_ENDPOINT_URL', None)
            self.bucket_name = os.getenv('S3_BUCKET_NAME')
            self.access_key = os.getenv('S3_ACCESS_KEY_ID')
            self.secret_key = os.getenv('S3_SECRET_ACCESS_KEY')
            self.region = os.getenv('S3_REGION', 'us-east-1')
            self.path_prefix = os.getenv('S3_PATH_PREFIX', '').strip('/')
            self.public_read = os.getenv('S3_PUBLIC_READ', 'true').lower() == 'true'
            
            if not all([self.bucket_name, self.access_key, self.secret_key]):
                print("Warning: S3 enabled but missing configuration. Disabling S3 uploads.")
                self.enabled = False
            else:
                # Initialize S3 client
                self.s3_client = boto3.client(
                    's3',
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region
                )
                print(f"S3 storage initialized: {self.bucket_name}")
                if self.endpoint_url:
                    print(f"Using custom endpoint: {self.endpoint_url}")
    
    def upload_file(self, local_path, s3_key):
        """Upload a file to S3"""
        if not self.enabled:
            return None
        
        try:
            # Add path prefix if configured
            if self.path_prefix:
                s3_key = f"{self.path_prefix}/{s3_key}"
            
            # Determine content type
            content_type, _ = mimetypes.guess_type(local_path)
            if not content_type:
                content_type = 'application/octet-stream'
            
            # Upload parameters
            extra_args = {
                'ContentType': content_type
            }
            
            if self.public_read:
                extra_args['ACL'] = 'public-read'
            
            # Upload file
            self.s3_client.upload_file(
                local_path,
                self.bucket_name,
                s3_key,
                ExtraArgs=extra_args
            )
            
            # Generate URL
            if self.endpoint_url:
                # Custom endpoint (like R2)
                url = f"{self.endpoint_url}/{self.bucket_name}/{s3_key}"
            else:
                # Standard AWS S3
                url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{s3_key}"
            
            return url
            
        except ClientError as e:
            print(f"Error uploading to S3: {e}")
            return None
    
    def upload_directory(self, local_dir, s3_prefix):
        """Upload an entire directory to S3"""
        if not self.enabled:
            return {}
        
        uploaded_files = {}
        
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                local_path = os.path.join(root, file)
                # Calculate S3 key maintaining directory structure
                relative_path = os.path.relpath(local_path, local_dir)
                s3_key = os.path.join(s3_prefix, relative_path).replace('\\', '/')
                
                url = self.upload_file(local_path, s3_key)
                if url:
                    uploaded_files[relative_path] = url
        
        return uploaded_files


class TMDBPosterGenerator:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/w500"
        self.cached_posters = []  # Cache for reusing posters
        self.cache_lock = threading.Lock()  # Thread safety for cache
        self.s3_storage = S3Storage()  # Initialize S3 storage
        
    def fetch_popular_content(self, count=12):
        """Fetch a mix of popular movies and TV series from TMDB"""
        content = []
        
        # Calculate how many of each type to fetch
        movies_count = count // 2
        tv_count = count - movies_count
        
        # Fetch popular movies from multiple pages for variety
        print("Fetching movies...")
        for page in range(1, 4):  # Get from first 3 pages
            movies_url = f"{self.base_url}/movie/popular?api_key={self.api_key}&page={page}"
            try:
                response = requests.get(movies_url)
                if response.status_code == 200:
                    movies = response.json()['results']
                    content.extend(movies)
                    if len(content) >= movies_count:
                        break
            except Exception as e:
                print(f"Error fetching movies page {page}: {e}")
        
        # Fetch popular TV shows from multiple pages
        print("Fetching TV series...")
        tv_content = []
        for page in range(1, 4):  # Get from first 3 pages
            tv_url = f"{self.base_url}/tv/popular?api_key={self.api_key}&page={page}"
            try:
                response = requests.get(tv_url)
                if response.status_code == 200:
                    tv_shows = response.json()['results']
                    tv_content.extend(tv_shows)
                    if len(tv_content) >= tv_count:
                        break
            except Exception as e:
                print(f"Error fetching TV shows page {page}: {e}")
        
        # Mix movies and TV shows
        content = content[:movies_count] + tv_content[:tv_count]
        
        # Shuffle for variety
        random.shuffle(content)
        
        print(f"Fetched {len(content)} items ({movies_count} movies, {tv_count} TV series)")
        return content[:count]
    
    def download_poster(self, poster_path):
        """Download poster image from TMDB"""
        if not poster_path:
            return None
        
        full_url = f"{self.image_base_url}{poster_path}"
        try:
            response = requests.get(full_url)
            if response.status_code == 200:
                return Image.open(io.BytesIO(response.content))
        except Exception as e:
            print(f"Error downloading poster: {e}")
        return None
    
    def fetch_and_cache_posters(self, count=40):
        """Fetch posters once and cache them for reuse with parallel downloads"""
        if self.cached_posters:
            return self.cached_posters
        
        print("\nFetching diverse content from TMDB (one-time fetch)...")
        content = self.fetch_popular_content(count=count)
        
        # Prepare download tasks
        download_tasks = []
        for item in content:
            poster_path = item.get('poster_path')
            if poster_path:
                title = item.get('title') or item.get('name', 'Unknown')
                download_tasks.append((poster_path, title))
        
        print(f"\nDownloading {len(download_tasks)} posters (5 concurrent downloads)...")
        
        # Download posters in parallel with max 5 concurrent downloads
        downloaded_count = 0
        lock = threading.Lock()
        
        def download_with_progress(task_data):
            poster_path, title = task_data
            poster = self.download_poster(poster_path)
            if poster:
                with lock:
                    nonlocal downloaded_count
                    downloaded_count += 1
                    print(f"[{downloaded_count}/{len(download_tasks)}] Downloaded: {title}")
                return poster
            return None
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_task = {executor.submit(download_with_progress, task): task 
                            for task in download_tasks}
            
            for future in as_completed(future_to_task):
                poster = future.result()
                if poster:
                    self.cached_posters.append(poster)
        
        print(f"\nCached {len(self.cached_posters)} posters for reuse")
        return self.cached_posters
    
    def create_tilted_grid_wallpaper(self, device_name, width, height, scale_factor=1):
        """Create a tilted poster grid wallpaper"""
        # Scale up for high resolution
        width = int(width * scale_factor)
        height = int(height * scale_factor)
        
        print(f"\nCreating {device_name} wallpaper ({width}x{height} @ {scale_factor}x)...")
        
        # Fixed poster dimensions for consistency
        base_poster_width = 200
        base_poster_height = 300
        gap = int(5 * scale_factor)  # Minimal gap between posters
        
        # Scale poster size based on device type and dimensions
        aspect_ratio = width / height
        
        # Detect device type and adjust accordingly
        if width > 3000:  # 4K displays
            poster_scale = 1.2
        elif width > 2000:  # QHD displays
            poster_scale = 1.0
        elif width > 1500:  # FHD displays
            poster_scale = 0.8
        elif aspect_ratio < 0.6:  # Phone displays (portrait)
            # Make posters larger for phones
            if height > 2500:  # Large phones
                poster_scale = 1.0
            else:  # Standard phones
                poster_scale = 0.9
        else:  # Tablets and other displays
            poster_scale = 0.7
        
        # Special handling for specific device types
        if "iPhone" in device_name or "Android" in device_name:
            # For mobile devices, make posters larger and reduce count
            poster_scale *= 1.3
            gap = int(8 * scale_factor)  # Slightly larger gap for mobile
        
        poster_width = int(base_poster_width * poster_scale * scale_factor)
        poster_height = int(base_poster_height * poster_scale * scale_factor)
        
        # Calculate how many posters we need to fill the rotated canvas
        # We need to create a canvas larger than the final size to account for rotation
        angle = -15  # Tilt angle
        angle_rad = math.radians(abs(angle))
        
        # Calculate the expanded dimensions needed to ensure full coverage after rotation
        diagonal = math.sqrt(width**2 + height**2)
        expanded_width = int(diagonal * 1.2)
        expanded_height = int(diagonal * 1.2)
        
        # Calculate grid dimensions based on expanded canvas
        cols = (expanded_width // (poster_width + gap)) + 2
        rows = (expanded_height // (poster_height + gap)) + 2
        
        # Use cached posters (thread-safe access)
        with self.cache_lock:
            if not self.cached_posters:
                print(f"Warning: No cached posters available for {device_name}")
                return None
            # Create a copy of cached posters for this thread
            posters = [poster.copy() if poster else None for poster in self.cached_posters]
        
        # Create the grid canvas with black background
        grid_canvas = Image.new('RGB', (expanded_width, expanded_height), (0, 0, 0))
        
        # Fill the entire canvas with posters, repeating if necessary
        poster_index = 0
        for row in range(rows):
            for col in range(cols):
                if poster_index >= len(posters):
                    poster_index = 0  # Loop back to start
                
                # Calculate position
                x = col * (poster_width + gap)
                y = row * (poster_height + gap)
                
                # Skip if poster is None
                if posters[poster_index] is None:
                    poster_index += 1
                    continue
                    
                # Resize poster to current dimensions
                try:
                    resized_poster = posters[poster_index].resize(
                        (poster_width, poster_height), 
                        Image.LANCZOS
                    )
                except Exception as e:
                    print(f"Error resizing poster {poster_index}: {e}")
                    poster_index += 1
                    continue
                
                # Paste the poster directly without shadow
                grid_canvas.paste(resized_poster, (x, y))
                poster_index += 1
        
        # Rotate the entire grid
        rotated_grid = grid_canvas.rotate(angle, expand=True, fillcolor=(0, 0, 0), resample=Image.BICUBIC)
        
        # Calculate center crop to get final dimensions
        rotated_width, rotated_height = rotated_grid.size
        crop_x = (rotated_width - width) // 2
        crop_y = (rotated_height - height) // 2
        
        # Crop to final size
        final_canvas = rotated_grid.crop((
            crop_x, 
            crop_y, 
            crop_x + width, 
            crop_y + height
        ))
        
        # No vignette effect - keep clean poster grid
        
        # Only create temp directories if S3 is disabled (for local storage)
        if not self.s3_storage.enabled:
            base_dir = './backgrounds'
            os.makedirs(f'{base_dir}/original', exist_ok=True)
            os.makedirs(f'{base_dir}/webp', exist_ok=True)
            os.makedirs(f'{base_dir}/jpeg', exist_ok=True)
        else:
            # Use temp directory for S3-only mode
            import tempfile
            base_dir = tempfile.mkdtemp()
        
        filename_base = device_name.lower().replace(' ', '_')
        
        # Save original PNG to temp location
        if not self.s3_storage.enabled:
            original_path = f"{base_dir}/original/{filename_base}.png"
        else:
            original_path = f"{base_dir}/{filename_base}_original.png"
        
        final_canvas.save(original_path, 'PNG', quality=95, optimize=False)
        original_size = os.path.getsize(original_path) / (1024 * 1024)  # MB
        
        # Determine target file size based on resolution
        total_pixels = width * height
        if total_pixels > 8000000:  # 4K and above
            target_size_kb = 2000  # 2MB
        elif total_pixels > 4000000:  # QHD
            target_size_kb = 1400  # 1.4MB
        elif total_pixels > 2000000:  # FHD
            target_size_kb = 1000  # 1MB
        elif total_pixels > 1000000:  # HD/Tablets
            target_size_kb = 800   # 800KB
        else:  # Mobile devices
            target_size_kb = 500   # 500KB
        
        # Save JPEG with optimal quality for target size first
        if not self.s3_storage.enabled:
            jpeg_path = f"{base_dir}/jpeg/{filename_base}.jpg"
        else:
            jpeg_path = f"{base_dir}/{filename_base}.jpg"
        jpeg_quality = 95
        
        # Binary search for optimal JPEG quality
        min_quality = 50
        max_quality = 95
        
        while max_quality - min_quality > 5:
            test_quality = (min_quality + max_quality) // 2
            final_canvas.save(jpeg_path, 'JPEG', quality=test_quality, optimize=True)
            test_size_kb = os.path.getsize(jpeg_path) / 1024
            
            if test_size_kb > target_size_kb:
                max_quality = test_quality
            else:
                min_quality = test_quality
                jpeg_quality = test_quality
        
        # Final save with optimal quality
        final_canvas.save(jpeg_path, 'JPEG', quality=jpeg_quality, optimize=True)
        jpeg_size_kb = os.path.getsize(jpeg_path) / 1024
        
        # Save WebP version from JPEG for better optimization
        if not self.s3_storage.enabled:
            webp_path = f"{base_dir}/webp/{filename_base}.webp"
        else:
            webp_path = f"{base_dir}/{filename_base}.webp"
        # Open the optimized JPEG and convert to WebP
        with Image.open(jpeg_path) as jpeg_img:
            webp_quality = 90 if target_size_kb > 1000 else 85
            jpeg_img.save(webp_path, 'WebP', quality=webp_quality, method=6)
        webp_size_kb = os.path.getsize(webp_path) / 1024
        
        print(f"Saved {filename_base}:")
        print(f"  • Resolution: {width}x{height} (target: {target_size_kb}KB)")
        print(f"  • Original PNG: {original_size:.1f}MB")
        print(f"  • JPEG: {jpeg_size_kb:.0f}KB (quality={jpeg_quality})")
        print(f"  • WebP: {webp_size_kb:.0f}KB (from JPEG, quality={webp_quality})")
        
        # Upload to S3 if enabled, then clean up temp files
        if self.s3_storage.enabled:
            s3_urls = {}
            
            # Upload each format
            for format_name, file_path in [
                ('original', original_path),
                ('jpeg', jpeg_path),
                ('webp', webp_path)
            ]:
                s3_key = f"{format_name}/{filename_base}{os.path.splitext(file_path)[1]}"
                url = self.s3_storage.upload_file(file_path, s3_key)
                if url:
                    s3_urls[format_name] = url
                
                # Remove temp file after upload
                try:
                    os.remove(file_path)
                except OSError:
                    pass
            
            # Clean up temp directory
            try:
                os.rmdir(base_dir)
            except OSError:
                pass
            
            if s3_urls:
                print(f"  • Uploaded to S3:")
                for format_name, url in s3_urls.items():
                    print(f"    - {format_name}: {url}")
            
            # Return S3 URL instead of local path
            return s3_urls.get('original', list(s3_urls.values())[0] if s3_urls else None)
        
        return original_path  # Return the local path (S3 disabled)
    
    
    def create_all_device_sizes(self):
        """Create poster collages for various device sizes using multi-threading"""
        # Device configurations: (name, width, height, scale_factor)
        devices = [
            # Desktop displays
            ("Desktop_4K", 3840, 2160, 1),
            ("Desktop_QHD", 2560, 1440, 1.5),
            ("Desktop_FHD", 1920, 1080, 2),
            ("Laptop", 1366, 768, 2.5),
            
            # Tablet displays
            ("iPad_Pro_12.9", 2732, 2048, 1),
            ("iPad_Air", 2360, 1640, 1),
            ("iPad_Mini", 2266, 1488, 1),
            
            # Phone displays
            ("iPhone_14_Pro_Max", 1290, 2796, 1),
            ("iPhone_14", 1170, 2532, 1),
            ("Android_Large", 1440, 3200, 1),
            ("Android_Standard", 1080, 2400, 1),
        ]
        
        # Get number of CPU cores
        cpu_count = multiprocessing.cpu_count()
        max_workers = min(cpu_count, 4)  # Use up to 4 threads
        
        print(f"Generating poster collages using {max_workers} threads (detected {cpu_count} CPU cores)...")
        print("Creating high-resolution images with dynamic file sizes.\n")
        
        # First, fetch and cache all posters
        print("Pre-fetching all posters...")
        self.fetch_and_cache_posters()
        print(f"Ready to generate wallpapers with {len(self.cached_posters)} cached posters\n")
        
        generated_files = []
        
        # Process devices in parallel
        def generate_wallpaper_wrapper(device_info):
            device_name, width, height, scale = device_info
            try:
                return self.create_tilted_grid_wallpaper(device_name, width, height, scale)
            except Exception as e:
                print(f"Error generating wallpaper for {device_name}: {e}")
                import traceback
                traceback.print_exc()
                return None
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(generate_wallpaper_wrapper, devices))
            generated_files = [r for r in results if r is not None]
        
        print(f"\n✅ Generated {len(generated_files)} wallpapers!")
        print("\nAll images feature a tilted grid layout with mixed movies and TV series.")
        if self.s3_storage.enabled:
            print("\nFiles uploaded to S3 storage with structure:")
            print("  • original/ - Full quality PNG files")
            print("  • jpeg/ - Optimized JPEG files with dynamic quality")
            print("  • webp/ - WebP format (generated from JPEG for efficiency)")
        else:
            print("\nFiles saved in ./backgrounds/ with subdirectories:")
            print("  • original/ - Full quality PNG files")
            print("  • jpeg/ - Optimized JPEG files with dynamic quality")
            print("  • webp/ - WebP format (generated from JPEG for efficiency)")
        print("\nFile sizes are optimized for each device:")
        print("  • 4K displays: up to 2MB")
        print("  • QHD displays: up to 1.4MB")
        print("  • FHD displays: up to 1MB")
        print("  • Mobile devices: 500-800KB")
        
        # Summary message
        if self.s3_storage.enabled:
            print(f"\n✅ All {len(generated_files)} wallpapers uploaded to S3 storage (no local files saved)")
        else:
            print(f"\n✅ All {len(generated_files)} wallpapers saved locally")
        
        return generated_files

def main():
    # Get API key from environment variable
    API_KEY = os.getenv('TMDB_API_KEY', 'your_tmdb_api_key_here')
    
    if not API_KEY or API_KEY == 'your_tmdb_api_key_here':
        print("Error: TMDB_API_KEY not set in environment variables")
        print("Please set TMDB_API_KEY in your .env file or environment")
        return
    
    print("TMDB Poster Wallpaper Generator")
    print("="*32)
    print("Creating tilted grid wallpapers for multiple devices...")
    print()
    
    generator = TMDBPosterGenerator(API_KEY)
    generator.create_all_device_sizes()

if __name__ == "__main__":
    main()

