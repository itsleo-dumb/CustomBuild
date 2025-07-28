#!/usr/bin/env python3
"""
Script to clean up old build statuses and artifacts from CustomBuild system.
"""

import redis
import os
import sys
import shutil
from pathlib import Path

# Add parent directory to path to import CustomBuild modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def cleanup_redis_builds(redis_host='localhost', redis_port=6379, max_age_hours=24):
    """
    Clean up old build metadata from Redis.
    
    Args:
        redis_host: Redis host
        redis_port: Redis port  
        max_age_hours: Maximum age of builds to keep (in hours)
    """
    import time
    import dill
    
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=False)
    
    # Get all build metadata keys
    keys = r.keys("buildmeta-*")
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    
    cleaned_count = 0
    
    for key in keys:
        try:
            # Get the build info
            build_data = r.get(key)
            if build_data:
                build_info = dill.loads(build_data)
                
                # Check if build is too old
                age_seconds = current_time - build_info.time_created
                
                if age_seconds > max_age_seconds:
                    build_id = key.decode().replace("buildmeta-", "")
                    print(f"Cleaning up old build: {build_id} (age: {age_seconds/3600:.1f} hours)")
                    r.delete(key)
                    cleaned_count += 1
                elif build_info.progress.state.name == "RUNNING":
                    # Clean up stuck "RUNNING" builds older than 1 hour
                    if age_seconds > 3600:
                        build_id = key.decode().replace("buildmeta-", "")
                        print(f"Cleaning up stuck RUNNING build: {build_id}")
                        r.delete(key)
                        cleaned_count += 1
                        
        except Exception as e:
            print(f"Error processing key {key}: {e}")
    
    print(f"Cleaned up {cleaned_count} build entries from Redis")
    return cleaned_count

def cleanup_build_queue(redis_host='localhost', redis_port=6379):
    """
    Clean up stuck items in the build queue.
    
    Args:
        redis_host: Redis host
        redis_port: Redis port
    """
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=False)
    
    # Get queue length
    queue_length = r.llen("builds-queue")
    
    if queue_length > 0:
        print(f"Found {queue_length} items in build queue")
        # Clear the entire queue (since stuck items are problematic)
        cleared = r.delete("builds-queue")
        print(f"Cleared build queue: {cleared} key deleted")
        return queue_length
    else:
        print("Build queue is empty")
        return 0

def cleanup_by_status(redis_host='localhost', redis_port=6379, statuses_to_clean=None):
    """
    Clean up builds by their status.
    
    Args:
        redis_host: Redis host
        redis_port: Redis port
        statuses_to_clean: List of statuses to clean (e.g., ['FAILURE', 'ERROR'])
    """
    if statuses_to_clean is None:
        statuses_to_clean = ['FAILURE', 'ERROR']
    
    import time
    import dill
    
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=False)
    
    # Get all build metadata keys
    keys = r.keys("buildmeta-*")
    cleaned_count = 0
    
    for key in keys:
        try:
            # Get the build info
            build_data = r.get(key)
            if build_data:
                build_info = dill.loads(build_data)
                
                # Check if build status should be cleaned
                if build_info.progress.state.name in statuses_to_clean:
                    build_id = key.decode().replace("buildmeta-", "")
                    print(f"Cleaning up {build_info.progress.state.name} build: {build_id}")
                    r.delete(key)
                    cleaned_count += 1
                        
        except Exception as e:
            print(f"Error processing key {key}: {e}")
    
    print(f"Cleaned up {cleaned_count} builds with status in {statuses_to_clean}")
    return cleaned_count

def cleanup_all_builds(redis_host='localhost', redis_port=6379):
    """
    Nuclear option: Clean up ALL builds from Redis.
    
    Args:
        redis_host: Redis host
        redis_port: Redis port
    """
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=False)
    
    # Get all build metadata keys
    keys = r.keys("buildmeta-*")
    
    if keys:
        deleted = r.delete(*keys)
        print(f"Deleted ALL {deleted} build entries from Redis")
        return deleted
    else:
        print("No build entries found in Redis")
        return 0

def cleanup_orphaned_artifacts(artifacts_dir, redis_host='localhost', redis_port=6379):
    """
    Clean up artifact directories that don't have corresponding Redis entries.
    
    Args:
        artifacts_dir: Path to artifacts directory
        redis_host: Redis host
        redis_port: Redis port
    """
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=False)
    
    # Get all current build IDs from Redis
    redis_keys = r.keys("buildmeta-*")
    active_build_ids = set()
    for key in redis_keys:
        build_id = key.decode().replace("buildmeta-", "")
        active_build_ids.add(build_id)
    
    # Check artifacts directory for orphaned folders
    artifacts_path = Path(artifacts_dir)
    if not artifacts_path.exists():
        print(f"Artifacts directory {artifacts_dir} does not exist")
        return 0
    
    cleaned_count = 0
    for item in artifacts_path.iterdir():
        if item.is_dir():
            build_id = item.name
            if build_id not in active_build_ids:
                print(f"Removing orphaned artifact directory: {build_id}")
                shutil.rmtree(item)
                cleaned_count += 1
    
    print(f"Cleaned up {cleaned_count} orphaned artifact directories")
    return cleaned_count

def main():
    """Main cleanup function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Clean up old CustomBuild artifacts and metadata')
    parser.add_argument('--max-age-hours', type=int, default=24, 
                       help='Maximum age of builds to keep (hours)')
    parser.add_argument('--redis-host', default='localhost', help='Redis host')
    parser.add_argument('--redis-port', type=int, default=6379, help='Redis port')
    parser.add_argument('--artifacts-dir', 
                       default='/home/orangepi/CustomBuild/base/artifacts',
                       help='Path to artifacts directory')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be cleaned without actually doing it')
    parser.add_argument('--clean-failed', action='store_true',
                       help='Clean up FAILURE and ERROR status builds')
    parser.add_argument('--clean-queue', action='store_true',
                       help='Clean up stuck items in build queue')
    parser.add_argument('--nuclear', action='store_true',
                       help='Nuclear option: Clean up ALL builds (use with caution!)')
    
    args = parser.parse_args()
    
    print(f"CustomBuild Cleanup Tool")
    print(f"Max age: {args.max_age_hours} hours")
    print(f"Redis: {args.redis_host}:{args.redis_port}")
    print(f"Artifacts: {args.artifacts_dir}")
    print("=" * 50)
    
    if args.dry_run:
        print("DRY RUN MODE - No changes will be made")
    
    try:
        total_cleaned = 0
        
        # Nuclear option - clean everything
        if args.nuclear:
            if args.dry_run:
                print("Would delete ALL builds from Redis (DRY RUN)")
            else:
                print("WARNING: Nuclear option selected - cleaning ALL builds!")
                confirm = input("Are you sure? Type 'yes' to continue: ")
                if confirm.lower() == 'yes':
                    nuclear_cleaned = cleanup_all_builds(
                        redis_host=args.redis_host,
                        redis_port=args.redis_port
                    )
                    # Also clean all artifacts
                    artifacts_path = Path(args.artifacts_dir)
                    if artifacts_path.exists():
                        for item in artifacts_path.iterdir():
                            if item.is_dir():
                                print(f"Removing artifact directory: {item.name}")
                                shutil.rmtree(item)
                    total_cleaned = nuclear_cleaned
                else:
                    print("Nuclear cleanup cancelled")
                    return
        else:
            # Clean up Redis entries by age
            if not args.dry_run:
                redis_cleaned = cleanup_redis_builds(
                    redis_host=args.redis_host,
                    redis_port=args.redis_port,
                    max_age_hours=args.max_age_hours
                )
                total_cleaned += redis_cleaned
            else:
                print("Would clean up Redis build metadata by age (dry run)")
            
            # Clean up failed builds if requested
            if args.clean_failed:
                if not args.dry_run:
                    failed_cleaned = cleanup_by_status(
                        redis_host=args.redis_host,
                        redis_port=args.redis_port,
                        statuses_to_clean=['FAILURE', 'ERROR']
                    )
                    total_cleaned += failed_cleaned
                else:
                    print("Would clean up FAILURE and ERROR builds (dry run)")
            
            # Clean up build queue if requested
            if args.clean_queue:
                if not args.dry_run:
                    queue_cleaned = cleanup_build_queue(
                        redis_host=args.redis_host,
                        redis_port=args.redis_port
                    )
                    total_cleaned += queue_cleaned
                else:
                    print("Would clean up build queue (dry run)")
            
            # Clean up orphaned artifacts
            if not args.dry_run:
                artifacts_cleaned = cleanup_orphaned_artifacts(
                    artifacts_dir=args.artifacts_dir,
                    redis_host=args.redis_host,
                    redis_port=args.redis_port
                )
                total_cleaned += artifacts_cleaned
            else:
                print("Would clean up orphaned artifact directories (dry run)")
        
        print("=" * 50)
        if args.dry_run:
            print("DRY RUN completed - no changes made")
        else:
            print(f"Cleanup complete. Total items cleaned: {total_cleaned}")
        
    except Exception as e:
        print(f"Error during cleanup: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
