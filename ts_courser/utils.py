"""
Shared utility functions for file handling: image compression, validation helpers.
"""

from io import BytesIO
from PIL import Image
from django.core.files.uploadedfile import InMemoryUploadedFile


def compress_image(uploaded_file, max_size_mb=1, quality=80):
    """
    Compress an uploaded image if it exceeds max_size_mb using Pillow.

    Converts the image to JPEG (RGB) with the given quality, stripping
    metadata (optimize=True). If the file is already within the limit or
    compression fails, the original file is returned unchanged.

    Args:
        uploaded_file: Django UploadedFile (InMemoryUploadedFile /
                       TemporaryUploadedFile).
        max_size_mb: Size threshold in MB above which compression is applied.
        quality: JPEG quality (1-100).  Default 80 balances size vs fidelity.

    Returns:
        The (possibly compressed) UploadedFile, or the original on error.
    """
    # Only process image files
    content_type = getattr(uploaded_file, 'content_type', '')
    if not content_type or not content_type.startswith('image/'):
        return uploaded_file

    max_size_bytes = max_size_mb * 1024 * 1024
    if uploaded_file.size <= max_size_bytes:
        return uploaded_file

    try:
        # Reset file pointer before opening
        uploaded_file.seek(0)
        img = Image.open(uploaded_file)

        # Convert to RGB (drop alpha channel) so we can save as JPEG
        if img.mode in ('RGBA', 'P', 'LA'):
            # Create white background for transparency
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = rgb_img
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)

        # If the compressed version is still larger, keep original
        if output.getbuffer().nbytes >= uploaded_file.size:
            uploaded_file.seek(0)
            return uploaded_file

        # Build a new InMemoryUploadedFile from the compressed bytes
        compressed = InMemoryUploadedFile(
            output,
            'ImageField',
            uploaded_file.name.rsplit('.', 1)[0] + '.jpg',
            'image/jpeg',
            output.getbuffer().nbytes,
            None,
        )
        return compressed

    except Exception:
        # On any error return the original file
        uploaded_file.seek(0)
        return uploaded_file
