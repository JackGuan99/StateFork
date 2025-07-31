#!/bin/bash

CONTAINER=$1

if [ -z "$CONTAINER" ]; then
  echo "Usage: $0 <container_name_or_id>"
  exit 1
fi

# Get RW and RootFS size in bytes
rw=$(podman container inspect --size "$CONTAINER" --format '{{.SizeRw}}')
rootfs=$(podman container inspect --size "$CONTAINER" --format '{{.SizeRootFs}}')

# Format them to human-readable
rw_hr=$(numfmt --to=iec $rw)
rootfs_hr=$(numfmt --to=iec $rootfs)

# Get memory usage string (e.g., "120MiB / 1GiB") and extract first part
mem_usage=$(podman stats --no-stream --format "{{.MemUsage}}" "$CONTAINER" | cut -d' ' -f1)

# Final output
echo "Container: $CONTAINER"
echo "-----------------------------"
echo "Memory Usage:  $mem_usage"
echo "RW Layer:      $rw_hr"
echo "RootFS Size:   $rootfs_hr"

