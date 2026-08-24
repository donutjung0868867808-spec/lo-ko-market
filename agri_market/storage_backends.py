import os

import cloudinary
import cloudinary.uploader
from cloudinary_storage.storage import MediaCloudinaryStorage


class PrivateCloudinaryStorage(MediaCloudinaryStorage):
    """Cloudinary storage whose originals require signed authenticated URLs."""

    def _upload(self, name, content):
        options = {
            "use_filename": True,
            "resource_type": self._get_resource_type(name),
            "tags": self.TAG,
            "type": "authenticated",
        }
        folder = os.path.dirname(name)
        if folder:
            options["folder"] = folder
        return cloudinary.uploader.upload(content, **options)

    def _get_url(self, name):
        name = self._prepend_prefix(name)
        resource = cloudinary.CloudinaryResource(
            name,
            default_resource_type=self._get_resource_type(name),
            type="authenticated",
        )
        return resource.build_url(sign_url=True, secure=True)

    def delete(self, name):
        response = cloudinary.uploader.destroy(
            name,
            invalidate=True,
            resource_type=self._get_resource_type(name),
            type="authenticated",
        )
        return response["result"] == "ok"