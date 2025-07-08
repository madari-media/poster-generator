# TMDB Poster Generator

A Python application that automatically generates high-quality wallpapers using movie and TV show posters from The Movie Database (TMDB). The generated wallpapers feature a tilted grid layout and are optimized for different device sizes.

## What This Project Does

- Fetches popular movies and TV series data from TMDB API
- Downloads poster images and creates tilted grid wallpapers
- Generates wallpapers for multiple device types (Desktop 4K/QHD/FHD, Tablets, Mobile phones)
- Saves images in three formats: Original PNG, Optimized JPEG, and WebP
- Uploads wallpapers to S3-compatible storage (AWS S3, Cloudflare R2, etc.)
- Uses multi-threading for fast generation
- Automatically optimizes file sizes based on target device resolution

## Quick Start with Docker

### Using Pre-built Image

```bash
# Pull the latest image
docker pull ghcr.io/madari-media/poster-generator:latest

# Create environment file
cat > .env << EOF
TMDB_API_KEY=your_tmdb_api_key_here
S3_ENABLED=true
S3_ENDPOINT_URL=https://your-endpoint.com
S3_BUCKET_NAME=your-bucket-name
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
S3_REGION=auto
S3_PATH_PREFIX=wallpapers
S3_PUBLIC_READ=true
EOF

# Run the generator
docker run --env-file .env ghcr.io/madari-media/poster-generator:latest
```

### Using Docker Compose

```bash
# Clone the repository
git clone https://github.com/madari-media/poster-generator.git
cd poster-generator

# Copy and edit environment file
cp .env.example .env
# Edit .env with your configuration

# Run with Docker Compose
docker-compose up
```

## Configuration

Create a `.env` file with these variables:

```env
# Required: TMDB API Key (get from https://www.themoviedb.org/settings/api)
TMDB_API_KEY=your_api_key_here

# Optional: S3 Storage Configuration
S3_ENABLED=true
S3_ENDPOINT_URL=https://your-s3-endpoint.com
S3_BUCKET_NAME=your-bucket-name
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
S3_REGION=us-east-1
S3_PATH_PREFIX=wallpapers
S3_PUBLIC_READ=true
```

### For Cloudflare R2

```env
S3_ENDPOINT_URL=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
S3_REGION=auto
```

### For AWS S3

```env
# Leave S3_ENDPOINT_URL empty for AWS S3
S3_REGION=us-east-1
```

## Local Development

```bash
# Clone repository
git clone https://github.com/madari-media/poster-generator.git
cd poster-generator

# Install dependencies
pip install uv
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Run the generator
uv run python main.py
```

## Output

When S3 is enabled, files are uploaded to your bucket with this structure:
```
wallpapers/
├── original/          # Full quality PNG files (10-15MB)
├── jpeg/             # Optimized JPEG files (500KB-2MB)
└── webp/             # WebP format files (generated from JPEG)
```

When S3 is disabled, files are saved locally in `./backgrounds/` directory.

## Requirements

- TMDB API Key (free from https://www.themoviedb.org/settings/api)
- Optional: S3-compatible storage credentials
- Docker (for containerized deployment)
- Python 3.11+ (for local development)

