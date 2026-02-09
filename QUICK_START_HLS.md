# 🎬 Quick Start: HLS Video Streaming

## TL;DR - How the New System Works

### Current System (Still Works!)
```
Admin uploads movie → Poster/Banner to Firebase, Video to R2 → Save URLs → Done
```

### New HLS System (Add-on)
```
After admin uploads → Click "Convert to HLS" → Backend processes → HLS streaming ready
```

---

## 🚀 5-Minute Setup

### 1. Install FFmpeg
```bash
sudo apt install ffmpeg
ffmpeg -version  # Verify
```

### 2. Install Python Packages
```bash
pip install ffmpeg-python==0.2.0 aiohttp==3.9.1
```

### 3. Register Routes
Add to `app/api/v1/router.py`:
```python
from .video_upload_hls import router as video_hls_router

api_router.include_router(
    video_hls_router,
    prefix="/video",
    tags=["Video HLS"]
)
```

### 4. Test It
```bash
# Convert an existing movie to HLS
curl -X POST "http://localhost:8000/api/v1/video/convert-existing-video" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "content_type=movie" \
  -F "content_id=1"

# Check status
curl "http://localhost:8000/api/v1/video/processing-status/{job_id}"
```

---

## 📋 How Admin Uses It

### Scenario 1: Upload New Movie

**Step 1:** Use existing admin panel (NO CHANGES)
```
Fill form → Upload poster, banner, video → Submit
```
Result: Movie created with MP4 video

**Step 2:** Convert to HLS (NEW)
```
Click "Convert to HLS" button → Wait 5-10 minutes → Done
```
Result: Movie now has adaptive streaming

### Scenario 2: Batch Convert Existing Movies

Run script overnight:
```bash
for id in 1 2 3 4 5; do
  curl -X POST "/api/v1/video/convert-existing-video" \
    -F "content_type=movie" -F "content_id=$id"
  sleep 600  # Wait 10 minutes between each
done
```

---

## 🎯 What Happens Behind the Scenes

```
1. Admin clicks "Convert to HLS"
      ↓
2. Backend downloads original MP4 from R2
      ↓
3. FFmpeg transcodes to multiple qualities:
   - 360p (mobile data saver)
   - 480p (SD)
   - 720p (HD)
   - 1080p (Full HD)
      ↓
4. Creates ~1,200 small video segments
      ↓
5. Uploads all segments to R2 → hls/movies/123/
      ↓
6. Updates database:
   video_url = "https://media.zentrya.africa/hls/movies/123/master.m3u8"
      ↓
7. Mobile app automatically uses HLS (no code changes)
```

---

## 📊 Before vs After

### Before (MP4)
- File: `https://media.zentrya.africa/videos/movie.mp4` (3.5 GB)
- User on 3G: Downloads 3.5 GB (buffers, wastes data)
- User on WiFi: Downloads 3.5 GB (OK)
- Quality: Fixed 1080p (no options)

### After (HLS)
- File: `https://media.zentrya.africa/hls/movies/123/master.m3u8`
- User on 3G: Auto uses 360p (~500 MB - **85% savings**)
- User on WiFi: Auto uses 1080p (full quality)
- Quality: Adaptive (switches based on connection)

---

## ✅ Checklist

- [ ] FFmpeg installed (`ffmpeg -version`)
- [ ] Python packages installed (`pip list | grep ffmpeg`)
- [ ] Routes registered in `router.py`
- [ ] Backend restarted
- [ ] Test convert one movie
- [ ] Verify HLS URL in database
- [ ] Test playback on mobile
- [ ] Convert remaining movies gradually

---

## 🆘 Troubleshooting

### "FFmpeg not found"
```bash
which ffmpeg
# If empty:
sudo apt install ffmpeg
```

### "Processing stuck at 0%"
```bash
# Check logs
tail -f /var/log/backend.log

# Check if FFmpeg works
ffmpeg -i test.mp4 -t 10 output.mp4
```

### "Job failed"
- Check video file is valid MP4
- Check disk space: `df -h`
- Check R2 credentials in `.env`

---

## 📞 Need Help?

See full documentation:
- [HLS_MIGRATION_GUIDE.md](./HLS_MIGRATION_GUIDE.md) - Complete guide
- [WORKFLOW_COMPARISON.md](./WORKFLOW_COMPARISON.md) - Detailed comparison

Your current system works exactly as before. HLS is an optional add-on that makes streaming better!
