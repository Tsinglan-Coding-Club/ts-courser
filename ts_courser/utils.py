"""
Shared utility functions for file handling: image compression, validation helpers.
"""

from io import BytesIO
from pathlib import Path
import warnings

from django.utils.text import get_valid_filename
from PIL import Image, UnidentifiedImageError
from django.core.files.uploadedfile import InMemoryUploadedFile


ALLOWED_IMAGE_FORMATS = {
    'JPEG': ('jpg', 'image/jpeg'),
    'PNG': ('png', 'image/png'),
    'GIF': ('gif', 'image/gif'),
    'WEBP': ('webp', 'image/webp'),
}


class ImageUploadValidationError(ValueError):
    """Raised when an uploaded file is not a safe, supported raster image."""


def validate_and_reencode_image(
    uploaded_file,
    *,
    max_size_bytes=2 * 1024 * 1024,
    max_pixels=16_000_000,
    max_width=4096,
    max_height=4096,
    crop_aspect_ratio=None,
):
    """Validate and re-encode a raster upload using its detected file format.

    Only JPEG, PNG, GIF, and WebP uploads are accepted. The browser supplied
    filename and content type are not trusted: Pillow identifies the format,
    then the image is decoded and written to a fresh file with a safe
    extension and MIME type. Invalid, oversized, or excessively large images
    raise :class:`ImageUploadValidationError`. When ``crop_aspect_ratio`` is
    supplied as ``(width, height)``, images taller than that ratio are cropped
    vertically around their centre. The original width is always preserved.
    """
    if not uploaded_file or uploaded_file.size > max_size_bytes:
        raise ImageUploadValidationError(
            'Image file size must be within the allowed limit.'
        )

    try:
        uploaded_file.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(uploaded_file) as verification_image:
                image_format = verification_image.format
                verification_image.verify()

        if image_format not in ALLOWED_IMAGE_FORMATS:
            raise ImageUploadValidationError(
                'Unsupported image type. Use JPEG, PNG, GIF, or WebP.'
            )

        uploaded_file.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(uploaded_file) as source_image:
                width, height = source_image.size
                if (
                    width < 1
                    or height < 1
                    or width > max_width
                    or height > max_height
                    or width * height > max_pixels
                ):
                    raise ImageUploadValidationError(
                        'Image dimensions exceed the allowed limit.'
                    )
                source_image.load()
                image = source_image.copy()
    except ImageUploadValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageUploadValidationError('Image dimensions exceed the allowed limit.')
    except (OSError, UnidentifiedImageError, ValueError):
        raise ImageUploadValidationError('Upload is not a valid image file.')
    finally:
        uploaded_file.seek(0)

    if crop_aspect_ratio is not None:
        try:
            ratio_width, ratio_height = crop_aspect_ratio
            if ratio_width <= 0 or ratio_height <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(
                'crop_aspect_ratio must contain two positive numbers.'
            ) from None

        width, height = image.size
        target_height = round(width * ratio_height / ratio_width)
        if 0 < target_height < height:
            top = (height - target_height) // 2
            image = image.crop((0, top, width, top + target_height))

    extension, content_type = ALLOWED_IMAGE_FORMATS[image_format]
    if image_format == 'JPEG':
        if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
            rgba_image = image.convert('RGBA')
            background = Image.new('RGB', image.size, 'white')
            background.paste(rgba_image, mask=rgba_image.getchannel('A'))
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
    elif image_format == 'GIF':
        image = image.convert('P', palette=Image.ADAPTIVE)
    elif image_format == 'WEBP' and image.mode not in ('RGB', 'RGBA'):
        image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')

    output = BytesIO()
    try:
        save_kwargs = {'format': image_format, 'optimize': True}
        if image_format in ('JPEG', 'WEBP'):
            save_kwargs['quality'] = 80
        image.save(output, **save_kwargs)
    except OSError as exc:
        raise ImageUploadValidationError('Upload could not be processed as an image.') from exc

    output_size = output.tell()
    if output_size > max_size_bytes:
        raise ImageUploadValidationError(
            'Processed image file size exceeds the allowed limit.'
        )
    output.seek(0)

    original_stem = get_valid_filename(Path(uploaded_file.name or 'image').stem)
    safe_name = f'{original_stem or "image"}.{extension}'
    return InMemoryUploadedFile(
        output,
        None,
        safe_name,
        content_type,
        output_size,
        None,
    )


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
