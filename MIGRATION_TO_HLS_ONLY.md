

# 🎬 Migration Guide: MP4 Upload → HLS-Only Upload

## Overview

This guide shows how to replace the old MP4 upload system with the new HLS-only system.

---

## 🔄 What's Changing

### OLD System (`movies.py`)
```python
POST /api/v1/movies/create-with-files
    ↓
Uploads:
- Video MP4 → Cloudflare R2 (stored as-is)
- Trailer MP4 → Cloudflare R2
- Poster → Firebase
- Banner → Firebase
    ↓
Database: video_url = "https://media.zentrya.africa/videos/abc.mp4"
    ↓
Mobile: Plays MP4 directly
```

### NEW System (`movies_hls.py`)
```python
POST /api/v1/movies/create-with-hls
    ↓
Uploads:
- Video MP4 → Temp file → Convert to HLS → Delete MP4
- Trailer MP4 → Cloudflare R2 (stays MP4)
- Poster → Firebase
- Banner → Firebase
    ↓
Background HLS Processing:
- Transcode to 360p, 480p, 720p, 1080p
- Upload HLS segments to R2
- Delete temp MP4
    ↓
Database: video_url = "https://media.zentrya.africa/hls/movies/123/master.m3u8"
    ↓
Mobile: Adaptive HLS streaming
```

---

## 📋 Step-by-Step Migration

### Step 1: Install Dependencies (if not done)

```bash
# Install FFmpeg
sudo apt update && sudo apt install ffmpeg

# Install Python packages
pip install ffmpeg-python==0.2.0 aiohttp==3.9.1

# Verify FFmpeg
ffmpeg -version
```

### Step 2: Register New Routes

**Option A: Replace old movies endpoint**

Edit `app/api/v1/router.py`:

```python
# Comment out old movies route
# from .movies import router as movies_router

# Add new HLS-only movies route
from .movies_hls import router as movies_router

# Keep the same registration
api_router.include_router(movies_router)
```

**Option B: Run both side-by-side (testing)**

Edit `app/api/v1/router.py`:

```python
# Old endpoint (keep for backward compatibility)
from .movies import router as movies_old_router
api_router.include_router(
    movies_old_router,
    prefix="/movies-old",
    tags=["Movies (Old - MP4)"]
)

# New endpoint (HLS-only)
from .movies_hls import router as movies_router
api_router.include_router(movies_router)  # Uses /movies prefix
```

### Step 3: Update Admin Panel

Change the upload endpoint in your admin panel:

**Before:**
```javascript
POST /api/v1/movies/create-with-files

FormData:
- title, description, etc.
- video_file (MP4)
- trailer_file (MP4)
- poster_file (JPG)
- banner_file (JPG)
```

**After:**
```javascript
POST /api/v1/movies/create-with-hls

FormData (same fields):
- title, description, etc.
- video_file (MP4) ← Will be converted to HLS
- trailer_file (MP4)
- poster_file (JPG)
- banner_file (JPG)

Response includes:
{
  "movie": { ... },
  "hls_job": {
    "job_id": "abc-123",
    "status_endpoint": "/api/v1/movies/hls-status/abc-123"
  }
}
```

### Step 4: Add Processing Status UI (Admin Panel)

After movie is created, poll for HLS processing status:

```javascript
async function createMovie(formData) {
  // Upload movie
  const response = await fetch('/api/v1/movies/create-with-hls', {
    method: 'POST',
    body: formData
  });

  const data = await response.json();
  const jobId = data.hls_job.job_id;

  // Show "Processing..." message
  showProcessingMessage(data.movie.id);

  // Poll for status
  const interval = setInterval(async () => {
    const status = await fetch(`/api/v1/movies/hls-status/${jobId}`);
    const statusData = await status.json();

    updateProgressBar(statusData.progress);

    if (statusData.status === 'completed') {
      clearInterval(interval);
      showSuccess('Movie is ready for streaming!');
      refreshMovieList();
    } else if (statusData.status === 'failed') {
      clearInterval(interval);
      showError('Video processing failed: ' + statusData.message);
    }
  }, 2000); // Check every 2 seconds
}
```

### Step 5: Restart Backend

```bash
# Kill old process
pkill -f uvicorn

# Start with new routes
uvicorn app.main:app --reload
```

---

## 🎯 Key Differences

| Feature | Old (movies.py) | New (movies_hls.py) |
|---------|----------------|---------------------|
| **Endpoint** | `/movies/create-with-files` | `/movies/create-with-hls` |
| **Video Storage** | MP4 in R2 | HLS segments in R2 |
| **Response Time** | Immediate | 2-step (create + process) |
| **Movie Status** | Active immediately | Inactive until HLS ready |
| **video_url** | `.mp4` file | `.m3u8` playlist |
| **Processing** | None | Background HLS conversion |
| **Storage Size** | 3.5 GB (1 file) | 4.2 GB (~1,200 files) |
| **Mobile Streaming** | Fixed quality | Adaptive quality |

---

## 📊 Database Changes

### Movie Model Status Field

The new system uses `is_active` to track processing:

```python
# When movie is created
movie.is_active = False  # Not ready yet
movie.video_url = None   # No video yet

# After HLS processing completes
movie.is_active = True   # Ready for streaming
movie.video_url = "https://media.zentrya.africa/hls/movies/123/master.m3u8"
```

**Admin Panel Should:**
- Show "Processing..." badge for `is_active=False` movies
- Hide from public until `is_active=True`
- Display processing progress from job status endpoint

---

## 🔍 Admin Panel UI Changes

### Movie List View

**Before:**
```
┌────────────────────────────────────────┐
│ Avengers Endgame                      │
│ Status: Active ✅                      │
│ [Edit] [Delete]                        │
└────────────────────────────────────────┘
```

**After:**
```
┌────────────────────────────────────────┐
│ Avengers Endgame                      │
│ Status: Processing HLS ⏳ (45%)       │
│ [View Status] [Edit] [Delete]         │
└────────────────────────────────────────┘

Or when ready:

┌────────────────────────────────────────┐
│ Avengers Endgame                      │
│ Status: Active ✅ (HLS Ready)         │
│ [Edit] [Delete]                        │
└────────────────────────────────────────┘
```

### Upload Form

Add processing status display:

```html
<!-- After form submission -->
<div class="processing-status">
  <h3>Movie Created: {{ movie.title }}</h3>
  <p>Video is being converted to HLS format...</p>

  <div class="progress-bar">
    <div class="progress" style="width: {{ progress }}%"></div>
  </div>

  <p>{{ statusMessage }}</p>
  <p>Estimated time: 5-15 minutes</p>
</div>
```

---

## 🚀 Testing

### Test 1: Upload Small Video

```bash
curl -X POST "http://localhost:8000/api/v1/movies/create-with-hls" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "title=Test Movie" \
  -F "slug=test-movie" \
  -F "description=Test description" \
  -F "video_file=@small_test.mp4" \
  -F "poster_file=@poster.jpg"

# Response:
{
  "success": true,
  "movie": {
    "id": 123,
    "title": "Test Movie",
    "is_active": false,  # Not active yet
    "video_status": "processing"
  },
  "hls_job": {
    "job_id": "abc-123-def",
    "status_endpoint": "/api/v1/movies/hls-status/abc-123-def"
  }
}
```

### Test 2: Check Processing Status

```bash
# Poll every few seconds
curl "http://localhost:8000/api/v1/movies/hls-status/abc-123-def"

# Response (processing):
{
  "status": "processing",
  "progress": 45,
  "message": "Transcoding... 45%",
  "movie_id": 123
}

# Response (completed):
{
  "status": "completed",
  "progress": 100,
  "message": "Processing complete!",
  "movie_id": 123,
  "result": {
    "hls_url": "https://media.zentrya.africa/hls/movies/123/master.m3u8",
    "duration": 7200.5,
    "variants": [...]
  }
}
```

### Test 3: Verify Database

```sql
SELECT id, title, is_active, video_url FROM movies WHERE id = 123;

-- Before processing:
-- id | title      | is_active | video_url
-- 123| Test Movie | false     | NULL

-- After processing:
-- id | title      | is_active | video_url
-- 123| Test Movie | true      | https://media.zentrya.africa/hls/movies/123/master.m3u8
```

### Test 4: Play on Mobile

```typescript
// Old URL won't work (NULL)
// New URL (after processing):
<Media3VideoPlayerView
  videoUrl="https://media.zentrya.africa/hls/movies/123/master.m3u8"
  quality={-1}  // Adaptive
/>
```

---

## ⚠️ Important Notes

### 1. Trailers Stay as MP4

Trailers don't need HLS (they're usually short):

```python
# Trailers are uploaded to R2 as MP4 (not converted)
trailer_url = await storage_service.upload_file(
    trailer_file.file,
    trailer_file.filename,
    'video/mp4',
    file_category='trailer'  # Goes to R2 as MP4
)
```

### 2. Movies Are Inactive During Processing

```python
# Created but not visible to users
movie.is_active = False

# After HLS complete
movie.is_active = True  # Now visible
```

**Frontend should:**
- Hide inactive movies from public listings
- Show "Processing" in admin panel
- Allow editing metadata while processing

### 3. Processing Can Fail

Handle failures gracefully:

```javascript
if (statusData.status === 'failed') {
  // Movie exists but video failed
  // Admin can:
  // - Delete movie
  // - Re-upload video
  // - Edit and retry
}
```

### 4. Disk Space

Processing requires temporary disk space:

```
Original MP4: 3.5 GB
Temp during processing: 7-10 GB (multiple quality transcoding)
Final HLS: 4.2 GB in R2
Temp files deleted: -7 GB

Net change: +4.2 GB in R2, 0 local disk
```

---

## 🔄 Rollback Plan

If you need to go back to MP4 uploads:

### 1. Switch Routes Back

```python
# In app/api/v1/router.py
from .movies import router as movies_router  # Old system
# from .movies_hls import router as movies_router  # Comment out
```

### 2. Restart Backend

```bash
uvicorn app.main:app --reload
```

### 3. Update Admin Panel

Point upload form back to `/movies/create-with-files`

---

## ✅ Checklist

- [ ] FFmpeg installed
- [ ] Python packages installed
- [ ] New routes registered in `router.py`
- [ ] Backend restarted
- [ ] Admin panel updated to use new endpoint
- [ ] Processing status UI added to admin
- [ ] Tested with small video (< 100MB)
- [ ] Verified HLS playback on mobile
- [ ] Updated documentation for team
- [ ] Monitored first few uploads

---

## 📞 Support

If you encounter issues:

1. Check FFmpeg: `ffmpeg -version`
2. Check logs: `tail -f /var/log/backend.log`
3. Verify R2 credentials: `.env` file
4. Test endpoint: `curl /api/v1/movies/hls-status/{job_id}`

See also:
- [HLS_MIGRATION_GUIDE.md](./HLS_MIGRATION_GUIDE.md)
- [WORKFLOW_COMPARISON.md](./WORKFLOW_COMPARISON.md)

---

## 🎉 Benefits of HLS-Only System

✅ **No duplicate storage** - MP4 deleted after conversion
✅ **Better streaming** - Adaptive quality on mobile
✅ **Data savings** - 85% less bandwidth on 3G
✅ **Professional** - Netflix/YouTube quality
✅ **Future-proof** - Industry standard streaming

Your platform is now enterprise-grade! 🚀
