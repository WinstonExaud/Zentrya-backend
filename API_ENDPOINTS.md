# 🎬 Zentrya Backend API Endpoints

## Base URL

All API endpoints are prefixed with `/api/v1/`

---

## 🎥 Movies (HLS)

### Create Movie with HLS
```
POST /api/v1/movies/create-with-hls
```

**Request (multipart/form-data):**
```
Form Fields:
- title: string (required)
- slug: string (required)
- description: string (required)
- synopsis: string (optional)
- duration: int (optional)
- release_year: int (optional)
- rating: float (default: 0)
- content_rating: string (optional)
- language: string (default: "English")
- director: string (optional)
- production: string (optional)
- cast: string (JSON array, optional)
- category_id: int (optional)
- genre_ids: string (JSON array, optional)
- is_featured: bool (default: false)
- is_active: bool (default: false)

Files:
- video_file: file (required) - MP4 video
- trailer_file: file (optional) - MP4 trailer
- poster_file: file (optional) - Image
- banner_file: file (optional) - Image
```

**Response:**
```json
{
  "success": true,
  "message": "Movie created successfully. Video is being converted to HLS format.",
  "movie": {
    "id": 123,
    "title": "Avengers Endgame",
    "slug": "avengers-endgame",
    "poster_url": "https://firebasestorage.../poster.jpg",
    "banner_url": "https://firebasestorage.../banner.jpg",
    "trailer_url": "https://media.zentrya.africa/trailers/xyz.mp4",
    "is_active": false,
    "video_status": "processing"
  },
  "hls_job": {
    "job_id": "abc-123-def-456",
    "status_endpoint": "/api/v1/movies/hls-status/abc-123-def-456",
    "estimated_time": "5-15 minutes depending on video length"
  }
}
```

### Check HLS Processing Status
```
GET /api/v1/movies/hls-status/{job_id}
```

**Response (Processing):**
```json
{
  "status": "processing",
  "progress": 45,
  "message": "Transcoding... 45%",
  "movie_id": 123,
  "movie_title": "Avengers Endgame"
}
```

**Response (Completed):**
```json
{
  "status": "completed",
  "progress": 100,
  "message": "Processing complete!",
  "movie_id": 123,
  "result": {
    "hls_url": "https://media.zentrya.africa/hls/movies/123/master.m3u8",
    "duration": 7200.5,
    "variants": [
      {"quality": "360p", "bandwidth": 928000, "resolution": "640x360"},
      {"quality": "480p", "bandwidth": 1592000, "resolution": "854x480"},
      {"quality": "720p", "bandwidth": 2992000, "resolution": "1280x720"},
      {"quality": "1080p", "bandwidth": 5192000, "resolution": "1920x1080"}
    ],
    "files_uploaded": 1214,
    "processing_time_seconds": 245.3
  }
}
```

**Response (Failed):**
```json
{
  "status": "failed",
  "progress": 0,
  "message": "Processing failed: FFmpeg error...",
  "movie_id": 123
}
```

### List Movies
```
GET /api/v1/movies/list?skip=0&limit=100&sort=title&is_active=true
```

**Response:**
```json
{
  "movies": [...],
  "total": 150,
  "skip": 0,
  "limit": 100
}
```

### Get Single Movie
```
GET /api/v1/movies/{movie_id}
```

### Update Movie
```
PUT /api/v1/movies/{movie_id}
```

**Request (JSON):**
```json
{
  "title": "New Title",
  "description": "New description",
  "is_active": true
}
```

### Delete Movie
```
DELETE /api/v1/movies/{movie_id}
```

---

## 📊 Admin URL Mapping

If your admin panel is calling these URLs, update them:

| Old URL (Wrong) | New URL (Correct) |
|-----------------|-------------------|
| `/api/movies/upload` | `/api/v1/movies/create-with-hls` |
| `/api/movies/status/{id}` | `/api/v1/movies/hls-status/{job_id}` |
| `/api/movies` | `/api/v1/movies/list` |
| `/api/movies/{id}` | `/api/v1/movies/{id}` |

---

## 🔧 Quick Fix for Admin Panel

Update your admin API configuration:

### Before (Wrong):
```typescript
const API_BASE_URL = '/api';

// Upload movie
fetch('/api/movies/upload', {
  method: 'POST',
  body: formData
});
```

### After (Correct):
```typescript
const API_BASE_URL = '/api/v1';

// Upload movie
fetch('/api/v1/movies/create-with-hls', {
  method: 'POST',
  body: formData
});
```

---

## 🎯 Full Example (Admin Panel)

```typescript
async function uploadMovie(formData: FormData) {
  try {
    // Upload movie with HLS conversion
    const response = await fetch('/api/v1/movies/create-with-hls', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${adminToken}`
      },
      body: formData
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || 'Upload failed');
    }

    console.log('Movie created:', data.movie);
    console.log('HLS job:', data.hls_job);

    // Start polling for status
    const jobId = data.hls_job.job_id;
    pollHLSStatus(jobId);

    return data;

  } catch (error) {
    console.error('Upload error:', error);
    throw error;
  }
}

async function pollHLSStatus(jobId: string) {
  const interval = setInterval(async () => {
    try {
      const response = await fetch(`/api/v1/movies/hls-status/${jobId}`);
      const data = await response.json();

      console.log(`Processing: ${data.progress}%`);
      updateProgressBar(data.progress);

      if (data.status === 'completed') {
        clearInterval(interval);
        console.log('HLS conversion complete!', data.result);
        showSuccess('Movie is ready for streaming!');
        refreshMovieList();
      } else if (data.status === 'failed') {
        clearInterval(interval);
        console.error('HLS conversion failed:', data.message);
        showError(data.message);
      }

    } catch (error) {
      console.error('Status check error:', error);
    }
  }, 2000); // Poll every 2 seconds
}
```

---

## 🚨 Common Errors

### 404 Not Found
```
POST /api/movies/upload HTTP/1.1" 404 Not Found
```

**Problem:** Wrong URL - missing `/v1/` prefix or wrong endpoint name

**Fix:** Use `/api/v1/movies/create-with-hls`

### 401 Unauthorized
```
POST /api/v1/movies/create-with-hls HTTP/1.1" 401 Unauthorized
```

**Problem:** Missing or invalid admin token

**Fix:** Add Authorization header:
```typescript
headers: {
  'Authorization': `Bearer ${adminToken}`
}
```

### 422 Unprocessable Entity
```
POST /api/v1/movies/create-with-hls HTTP/1.1" 422
```

**Problem:** Missing required fields or wrong field types

**Fix:** Check all required fields are in FormData:
- `title` (string)
- `slug` (string)
- `description` (string)
- `video_file` (file)

---

## ✅ Testing with cURL

```bash
# Upload movie with HLS
curl -X POST "http://localhost:8000/api/v1/movies/create-with-hls" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -F "title=Test Movie" \
  -F "slug=test-movie" \
  -F "description=Test description" \
  -F "language=English" \
  -F "rating=5.0" \
  -F "video_file=@/path/to/video.mp4" \
  -F "poster_file=@/path/to/poster.jpg" \
  -F "banner_file=@/path/to/banner.jpg"

# Check processing status
curl "http://localhost:8000/api/v1/movies/hls-status/abc-123-def"

# List movies
curl "http://localhost:8000/api/v1/movies/list?limit=10"

# Get single movie
curl "http://localhost:8000/api/v1/movies/1"
```

---

## 📝 Summary

**Correct Base URL:** `/api/v1/`

**Main Endpoints:**
- Upload: `POST /api/v1/movies/create-with-hls`
- Status: `GET /api/v1/movies/hls-status/{job_id}`
- List: `GET /api/v1/movies/list`
- Get: `GET /api/v1/movies/{id}`
- Update: `PUT /api/v1/movies/{id}`
- Delete: `DELETE /api/v1/movies/{id}`

Update your admin panel to use these URLs! 🚀
