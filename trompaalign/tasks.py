from celery import shared_task

from trompaalign.solid import lookup_provider_from_profile, get_storage_from_profile, get_clara_listing_for_pod, \
    create_clara_container, upload_mei_to_pod


@shared_task(ignore_result=False)
def add_score(profile, score_url, title):
    """
    To add a score, we have the following possible methods:
      1. download the MEI from the browser, then create the Container in the browser, compute structure in the browser,
         upload MEI + Structure
      2. download MEI in the browser, create the container + upload the MEI and then trigger a backend python task
         which downloads the MEI, computes the structure, and uploads it
      3. trigger a backend command from the browser, which creates the container, downloads the MEI, computes the
         structure, uploads them both, and returns the URI of the new Container to the browser

    The structure is necessary before the first rehearsal. It's a summary of some of the data in the MEI file, in
    json-ld format.
    As we have existing code in python to compute structure and make containers/upload files, 3 is easiest,
    but if for example the specified MEI doesn't have a title, we can't prompt the user to enter something.
    Eventually we might want to move to 1. to have a more flexible process

    :param profile:
    :param score_url:
    :param title:
    :return:
    """
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    clara_container = get_clara_listing_for_pod(provider, profile, storage)
    if clara_container is None:
        create_clara_container(provider, profile, storage)

    return upload_mei_to_pod(provider, profile, storage, score_url, None, title)
