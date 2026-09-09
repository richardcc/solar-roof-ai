import torch

print("=" * 50)
print("PyTorch GPU Check")
print("=" * 50)

print(f"PyTorch version: {torch.__version__}")
print(f"CUDA version: {torch.version.cuda}")

cuda_available = torch.cuda.is_available()

print(f"CUDA available: {cuda_available}")

if cuda_available:
    print(f"GPU count: {torch.cuda.device_count()}")
    print(f"GPU name: {torch.cuda.get_device_name(0)}")

    print(
        f"Memory: "
        f"{torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB"
    )
else:
    print("No CUDA GPU detected")