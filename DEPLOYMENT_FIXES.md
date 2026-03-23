# Vercel Serverless Function Crash Fixes

## Root Causes Identified & Fixed

### 1. **File System Access Issue** (CRITICAL)
**Problem:** Logger was trying to write to `logs/app.log` on Vercel's read-only filesystem
**Fix in `app/utils/logger.py`:**
- Added check for `VERCEL` environment variable
- File logging is skipped on Vercel, only console output is used
- Wrapped in try-except for graceful fallback

### 2. **asyncio.Lock() at Import Time** (CRITICAL)
**Problem:** Creating `asyncio.Lock()` without an event loop causes crashes on import
**Fix in `app/core/proxy_pool.py`:**
- Changed `self._lock = asyncio.Lock()` to lazy initialization
- Added `_get_lock()` method that creates lock on first use
- Updated lock usage to `self._get_lock()`

### 3. **Startup Task Timing Issue**
**Problem:** Using `asyncio.create_task()` in startup doesn't wait for completion
**Fix in `main.py`:**
- Changed to direct `await proxy_pool.start()` with error handling
- Proxy pool now fails gracefully instead of crashing app

### 4. **Missing Timeouts**
**Problem:** Proxy fetching could hang indefinitely on Vercel
**Fix in `app/core/proxy_pool.py`:**
- Added 30s timeout for proxy source fetching
- Added 60s timeout for proxy testing
- Wrapped in `asyncio.wait_for()` with fallback

### 5. **SSL Verification Issues**
**Problem:** Some proxies fail with strict SSL verification
**Fix in `app/core/terabox.py`:**
- Smart SSL handling: disable only for SOCKS and unencrypted proxies
- Default to `verify=True` for HTTPS proxies

## New Features

### Health Check Endpoint
```bash
GET /health
```
Returns proxy pool status and uptime

### Manual Initialization Endpoint
```bash
POST /init
```
Manually warmup proxy pool after cold start

## Configuration Changes

### vercel.json Enhancements
- Set `PYTHONUNBUFFERED=1` for real-time logs
- Configured max lambda size: 50MB
- Set timeout: 60 seconds
- Allocated 3008MB memory

### New Files
- `.vercelignore` - Exclude unnecessary files from build
- `test_startup.py` - Startup verification script
- `DEPLOYMENT_FIXES.md` - This document

## Testing Before Deployment

Run the startup test:
```bash
python test_startup.py
```

Expected output:
```
✓ Config loaded: Terabox Direct Link API v2.0.0
✓ Logger initialized successfully
✓ Proxy pool initialized
✓ Terabox fetcher ready
✓ FastAPI app initialized
✅ All systems ready for deployment!
```

## Deployment Instructions

1. Push changes to your branch
2. Vercel will auto-detect and deploy
3. After deployment, call POST /init to warmup proxy pool
4. Test with GET /health to verify system status
5. API will use direct connection if proxies fail to load

## Fallback Behavior

If proxy pool initialization fails:
- App continues running (doesn't crash)
- Uses direct connection without proxy
- Logs warning but keeps functioning
- Can manually call POST /init later

## Monitoring

Check Vercel Function Logs:
- Look for "Proxy Pool Manager starting" - confirms startup
- Look for timeout warnings - indicates proxy source issues
- Health endpoint shows pool status

## Common Issues & Solutions

### Still seeing "Serverless Function has crashed"
1. Check Vercel logs for the actual error
2. Call POST /init to manually initialize
3. Check if TERABOX_APP_ID is set in environment variables

### Proxy pool always empty
- This is OK! App works with direct connection
- Proxy sources may be blocked in your region
- POST /init will retry initialization

### Timeout errors
- Vercel has 60s cold start limit
- Proxy fetching has 30s timeout
- If stuck, restart function or increase timeout in vercel.json

---

**Last Updated:** 2025-03-23
**Status:** Ready for deployment
