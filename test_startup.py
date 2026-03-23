#!/usr/bin/env python3
"""
Startup verification script for Vercel deployment
Tests all critical imports and initialization
"""

import sys
import os

def test_imports():
    """Test that all imports work without crashing"""
    print("[1/5] Testing core imports...")
    try:
        from app.core.config import settings
        print(f"  ✓ Config loaded: {settings.APP_NAME} v{settings.APP_VERSION}")
    except Exception as e:
        print(f"  ✗ Config import failed: {e}")
        return False
    
    print("[2/5] Testing logger...")
    try:
        from app.utils.logger import log
        log.info("✓ Logger initialized successfully")
    except Exception as e:
        print(f"  ✗ Logger failed: {e}")
        return False
    
    print("[3/5] Testing proxy pool...")
    try:
        from app.core.proxy_pool import proxy_pool
        print(f"  ✓ Proxy pool initialized: {type(proxy_pool)}")
    except Exception as e:
        print(f"  ✗ Proxy pool failed: {e}")
        return False
    
    print("[4/5] Testing Terabox core...")
    try:
        from app.core.terabox import terabox
        print(f"  ✓ Terabox fetcher ready: {type(terabox)}")
    except Exception as e:
        print(f"  ✗ Terabox failed: {e}")
        return False
    
    print("[5/5] Testing FastAPI app...")
    try:
        from main import app
        print(f"  ✓ FastAPI app initialized: {app.title}")
        print(f"  ✓ Routes available: {len(app.routes)}")
    except Exception as e:
        print(f"  ✗ App init failed: {e}")
        return False
    
    return True


if __name__ == "__main__":
    print("\n🔍 Vercel Startup Verification\n")
    
    success = test_imports()
    
    print("\n" + "="*50)
    if success:
        print("✅ All systems ready for deployment!")
        sys.exit(0)
    else:
        print("❌ Startup verification failed!")
        sys.exit(1)
