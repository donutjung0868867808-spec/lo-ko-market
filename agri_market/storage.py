from django.core.files.storage import storages


def private_storage():
    return storages["private"]