"""
scripts/check_training_env.py: Verification script for HINAKU training environment.
Checks installed package versions, CUDA availability, GPU specs, VRAM metrics,
and runs a 4-bit tensor operation with bitsandbytes on the GPU.
"""

import sys
import os

def check_env():
    print("=" * 60)
    print(" HINAKU Training Environment Verification")
    print("=" * 60)
    print(f"Python Executable : {sys.executable}")
    print(f"Python Version    : {sys.version.split()[0]}")

    errors = []

    # 1. Package Versions
    print("\n[1/4] Checking Installed Library Versions:")
    packages = ["torch", "transformers", "peft", "trl", "bitsandbytes", "accelerate", "datasets"]
    for pkg in packages:
        try:
            mod = __import__(pkg)
            version = getattr(mod, "__version__", "unknown")
            print(f"  - {pkg:<15}: {version}")
        except ImportError as e:
            print(f"  - {pkg:<15}: NOT INSTALLED ({e})")
            errors.append(pkg)

    if errors:
        print(f"\nERROR: Missing required packages: {', '.join(errors)}")
        sys.exit(1)

    import torch
    import bitsandbytes as bnb

    # 2. CUDA Availability & Hardware Info
    print("\n[2/4] Checking CUDA & GPU Details:")
    cuda_avail = torch.cuda.is_available()
    print(f"  - torch.cuda.is_available() : {cuda_avail}")

    if not cuda_avail:
        print("\nERROR: CUDA is not available to PyTorch. Training cannot proceed on GPU.")
        sys.exit(1)

    device_count = torch.cuda.device_count()
    device_id = 0
    gpu_name = torch.cuda.get_device_name(device_id)
    capability = torch.cuda.get_device_capability(device_id)
    cuda_version = torch.version.cuda

    print(f"  - PyTorch CUDA Version     : {cuda_version}")
    print(f"  - Device Count             : {device_count}")
    print(f"  - GPU Name                 : {gpu_name}")
    print(f"  - Compute Capability       : {capability[0]}.{capability[1]}")

    # 3. VRAM Inspection
    print("\n[3/4] Measuring VRAM:")
    free_bytes, total_bytes = torch.cuda.mem_get_info(device_id)
    free_gb = free_bytes / (1024 ** 3)
    total_gb = total_bytes / (1024 ** 3)
    used_gb = total_gb - free_gb

    print(f"  - Total VRAM               : {total_gb:.2f} GB ({total_bytes} bytes)")
    print(f"  - Free VRAM                : {free_gb:.2f} GB ({free_bytes} bytes)")
    print(f"  - Used VRAM                : {used_gb:.2f} GB")

    # 4. 4-bit Load Test with bitsandbytes
    print("\n[4/4] Running 4-bit bitsandbytes Load Test on GPU:")
    try:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        # Create a Linear4bit module (NF4 quantized weights)
        in_features = 128
        out_features = 64
        batch_size = 4

        print("  - Initializing bnb.nn.Linear4bit (NF4, fp16 compute)...")
        linear_4bit = bnb.nn.Linear4bit(
            in_features,
            out_features,
            bias=False,
            compute_dtype=torch.float16,
            quant_type="nf4"
        ).cuda()

        # Create input tensor on CUDA
        x = torch.randn(batch_size, in_features, dtype=torch.float16, device="cuda")

        # Execute forward pass through bitsandbytes 4-bit kernel
        y = linear_4bit(x)

        assert y.shape == (batch_size, out_features), f"Shape mismatch: {y.shape}"
        assert not torch.isnan(y).any(), "Output contains NaN"

        peak_vram = torch.cuda.max_memory_allocated() / (1024 ** 2)
        print(f"  - Forward pass output shape : {tuple(y.shape)}")
        print(f"  - Peak test allocation      : {peak_vram:.2f} MB")
        print("  - bitsandbytes 4-bit CUDA kernel execution: SUCCESSFUL")

    except Exception as e:
        print(f"\nERROR: bitsandbytes 4-bit execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 60)
    print(" Result: Environment is verified and ready for QLoRA training.")
    print("=" * 60)

if __name__ == "__main__":
    check_env()

