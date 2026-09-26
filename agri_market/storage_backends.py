import os

import cloudinary
import cloudinary.uploader
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.core.files.uploadedfile import UploadedFile


class FilenamePreservingCloudinaryStorage(MediaCloudinaryStorage):
    """Keep the original extension in Django while Cloudinary stores a public ID."""

    def _save(self, name, content):
        name = self._normalise_name(name)
        name = self._prepend_prefix(name)
        response = self._upload(name, UploadedFile(content, name))
        public_id = response["public_id"]
        extension = os.path.splitext(name)[1].lower()
        return public_id if not extension or public_id.lower().endswith(extension) else f"{public_id}{extension}"

    def _resource_and_format(self, name, **options):
        name = self._prepend_prefix(name)
        public_id, extension = os.path.splitext(name)
        resource = cloudinary.CloudinaryResource(
            public_id if extension else name,
            default_resource_type=self._get_resource_type(name),
            **options,
        )
        return resource, extension.lstrip(".")

    def delete(self, name):
        resource, _ = self._resource_and_format(name)
        options = {"invalidate": True, "resource_type": self._get_resource_type(name)}
        if resource.type:
            options["type"] = resource.type
        response = cloudinary.uploader.destroy(resource.public_id, **options)
        return response["result"] == "ok"


class PublicCloudinaryStorage(FilenamePreservingCloudinaryStorage):
    def _get_url(self, name):
        resource, extension = self._resource_and_format(name)
        options = {"secure": True}
        if extension:
            options["format"] = extension
        return resource.build_url(**options)


class PrivateCloudinaryStorage(FilenamePreservingCloudinaryStorage):
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
        resource, extension = self._resource_and_format(name, type="authenticated")
        options = {"sign_url": True, "secure": True}
        if extension:
            options["format"] = extension
        return resource.build_url(**options)
