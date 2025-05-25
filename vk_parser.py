import asyncio
from aiovk import API, TokenSession, UserLongPoll
import config
from logger import logger
import moderation
import os
import tempfile
import aiohttp # Import aiohttp for downloading media
import content_filter # Import content_filter
import shutil # Import shutil for cleanup

# Создаем временную директорию для хранения медиафайлов на время модерации VK
TEMP_VK_MEDIA_DIR = os.path.join(tempfile.gettempdir(), "newsbot_vk_media")
os.makedirs(TEMP_VK_MEDIA_DIR, exist_ok=True)


async def download_media(session, media_type, owner_id, media_id, access_key=None):
    """
    Downloads a single media file (photo or video) from VK.
    Returns the path to the downloaded file or None if failed.
    """
    api = API(session)
    download_url = None
    file_extension = None

    try:
        if media_type == 'photo':
            photos_str = f'{owner_id}_{media_id}'
            if access_key:
                photos_str += f'_{access_key}'

            response = await api.photos.getById(photos=photos_str)
            if response and isinstance(response, list) and response:
                photo = response[0]
                # Find the largest available size
                sizes = photo.get('sizes', [])
                if sizes:
                    largest_size = max(sizes, key=lambda s: s.get('width', 0) * s.get('height', 0))
                    download_url = largest_size.get('url')
                    file_extension = '.jpg'

        elif media_type == 'video':
            # For videos, the API response structure might be different
            # Need to fetch video details to get access to files
            # The 'videos' parameter expects 'owner_id_video_id'
            videos_str = f'{owner_id}_{media_id}'
            # VK API video.get might require additional parameters like 'access_key'
            # depending on privacy settings. We'll try without first.
            try:
                 response = await api.video.get(videos=videos_str)
                 if response and isinstance(response, dict) and 'items' in response and response['items']:
                     video = response['items'][0]
                     # The video files are often in the 'files' dict with different resolutions
                     # We might need to pick a suitable resolution or the mp4 file directly.
                     # Let's look for the first available mp4 URL.
                     files = video.get('files', {})
                     for key, url in files.items():
                          if url and key.endswith('mp4'):
                              download_url = url
                              file_extension = '.mp4'
                              break
                     if not download_url:
                          # If no mp4 found, try others (e.g., external host link)
                          download_url = video.get('player') # Fallback to player URL, though not ideal
                          file_extension = '.html' # Indicate it's likely an external player link

            except Exception as video_e:
                logger.warning(f"Failed to get VK video details for {owner_id}_{media_id}: {video_e}")
                # If initial video.get fails, try again with access_key if available
                if access_key:
                    try:
                        videos_str = f'{owner_id}_{media_id}_{access_key}'
                        response = await api.video.get(videos=videos_str)
                        if response and isinstance(response, dict) and 'items' in response and response['items']:
                            video = response['items'][0]
                            files = video.get('files', {})
                            for key, url in files.items():
                                if url and key.endswith('mp4'):
                                    download_url = url
                                    file_extension = '.mp4'
                                    break
                            if not download_url:
                                download_url = video.get('player')
                                file_extension = '.html'
                    except Exception as video_e_ak:
                        logger.error(f"Failed to get VK video details with access_key for {owner_id}_{media_id}: {video_e_ak}")

        if download_url and file_extension:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.get(download_url) as response:
                    if response.status == 200:
                        # Save to temporary file
                        temp_dir = os.path.join(TEMP_VK_MEDIA_DIR, f"vk_{owner_id}_{media_id}")
                        os.makedirs(temp_dir, exist_ok=True)
                        temp_file_path = os.path.join(temp_dir, f"{media_id}{file_extension}")
                        with open(temp_file_path, 'wb') as f:
                            while True:
                                chunk = await response.content.read(1024)
                                if not chunk:
                                    break
                                f.write(chunk)
                        logger.info(f"Downloaded VK media {media_type} {owner_id}_{media_id} to {temp_file_path}")
                        return temp_file_path
                    else:
                        logger.error(f"Failed to download VK media from {download_url}. Status: {response.status}")
        elif media_type in ['photo', 'video']:
             logger.warning(f"Could not find download URL for VK media {media_type} {owner_id}_{media_id}")

    except Exception as e:
        logger.error(f"Error downloading VK media {media_type} {owner_id}_{media_id}: {e}")

    return None


async def _extract_vk_message_data(session, vk_object):
    """
    Extracts standardized message data (channel_id, message_id, text, media_paths) from a VK object.
    Can handle VK Long Poll events (type 4) and wall post objects.
    """
    channel_id = None
    message_id = None
    text = ""
    attachments_dict = {}
    media_paths = []
    source_type = "vk"
    original_object = None # Keep track of the original object if needed later

    if isinstance(vk_object, list) and len(vk_object) >= 7 and vk_object[0] == 4: # Long Poll event
        message_id = vk_object[1]
        channel_id = vk_object[3] # peer_id
        text = vk_object[5]
        attachments_dict = vk_object[6]
        original_object = vk_object
        logger.debug(f"Extracted data from LP event: {channel_id}:{message_id}")

    elif isinstance(vk_object, dict) and 'id' in vk_object and 'owner_id' in vk_object: # Likely a wall post item
        message_id = vk_object.get('id')
        channel_id = vk_object.get('owner_id') # group/page ID (negative)
        text = vk_object.get('text', '')
        # Wall post attachments are in a list, each item having 'type' and details
        attachments_list = vk_object.get('attachments', [])
        # Convert list of attachments to a dict similar to LP for unified processing
        # Note: This is a simplification; not all LP attachment keys map directly.
        # We will process the list directly below.
        # attachments_dict = {f'attach{i+1}_type': att.get('type') for i, att in enumerate(attachments_list)}
        # for i, att in enumerate(attachments_list):
        #     if att.get('type') in ['photo', 'video']:
        #          # Format for photos/videos in wall post attachments is different
        #          # Need owner_id and media_id from the specific attachment object
        #          # photo/video objects usually have id and owner_id fields
        #          att_details = f"{att[att['type']].get('owner_id')}_{att[att['type']].get('id')}"
        #          if att[att['type']].get('access_key'):
        #              att_details += f"_{att[att['type']].get('access_key')}"
        #          attachments_dict[f'attach{i+1}'] = att_details
        original_object = vk_object
        logger.debug(f"Extracted data from wall post: {channel_id}:{message_id}")


    if channel_id is None or message_id is None:
        logger.warning(f"Could not extract essential data from VK object: {vk_object}")
        return None, None, "", [], "vk", None

    # Process attachments if it's a wall post object (list of dicts)
    if isinstance(vk_object, dict) and 'attachments' in vk_object:
        attachments_list = vk_object.get('attachments', [])
        for att in attachments_list:
            att_type = att.get('type')
            if att_type in ['photo', 'video']:
                 # Extract owner_id, media_id, access_key from the attachment object itself
                 media_obj = att.get(att_type)
                 if media_obj and isinstance(media_obj, dict):
                     owner_id = media_obj.get('owner_id')
                     media_id = media_obj.get('id')
                     access_key = media_obj.get('access_key')

                     if owner_id is not None and media_id is not None:
                         # Check if the media belongs to the source channel/group
                         if owner_id == channel_id: # Compare with the extracted channel_id
                              logger.info(f"Found VK media attachment in wall post: type={att_type}, owner={owner_id}, id={media_id}")
                              downloaded_path = await download_media(session, att_type, owner_id, media_id, access_key)
                              if downloaded_path:
                                  media_paths.append(downloaded_path)
                              else:
                                  logger.warning(f"Failed to download VK media {att_type} {owner_id}_{media_id}")
                         else:
                              logger.debug(f"Ignoring VK media attachment in wall post from different owner ({owner_id}) than peer ({channel_id})")
                     else:
                          logger.warning(f"Could not get owner_id or media_id from VK attachment {att}")

            # TODO: Handle other media types if needed (docs, audio, etc.)
            else:
                logger.debug(f"Ignoring unsupported VK attachment type in wall post: {att_type}")

    # Process attachments if it's a Long Poll event (dict in 6th element)
    elif isinstance(vk_object, list) and len(vk_object) >= 7 and vk_object[0] == 4:
         attachments_dict = vk_object[6]
         i = 1
         while f'attach{i}_type' in attachments_dict:
             attach_type = attachments_dict[f'attach{i}_type']
             attach_details = attachments_dict.get(f'attach{i}') # Format: owner_id_media_id or owner_id_media_id_access_key
             # access_key might be separate key or part of attach_details string
             access_key = attachments_dict.get(f'attach{i}_access_key')

             if attach_details:
                 try:
                     parts = attach_details.split('_')
                     owner_id = int(parts[0])
                     media_id = int(parts[1])
                     if len(parts) > 2 and not access_key:
                          access_key = parts[2]

                     if attach_type in ['photo', 'video']:
                         # Check if the media belongs to the source channel/group
                         if owner_id == channel_id: # Compare with the extracted channel_id
                             logger.info(f"Found VK media attachment in LP event: type={attach_type}, owner={owner_id}, id={media_id}")
                             downloaded_path = await download_media(session, attach_type, owner_id, media_id, access_key)
                             if downloaded_path:
                                 media_paths.append(downloaded_path)
                             else:
                                 logger.warning(f"Failed to download VK media {attach_type} {owner_id}_{media_id}")
                         else:
                              logger.debug(f"Ignoring VK media attachment in LP event from different owner ({owner_id}) than peer ({channel_id})")
                     else:
                         logger.debug(f"Ignoring unsupported VK attachment type in LP event: {attach_type}")

                 except Exception as parse_e:
                     logger.error(f"Error parsing VK attachment details '{attach_details}': {parse_e}")

             i += 1

    return channel_id, message_id, text, media_paths, source_type, original_object


async def _process_vk_message(session, channel_id, message_id, text, media_paths):
    """
    Handle processed VK message data and send to moderation.
    """
    try:
        logger.info(f"Processing VK message from {channel_id} (ID: {message_id}): {text[:100]}... with {len(media_paths)} media files")

        # Apply content filter
        try:
            is_filtered = await content_filter.check_content(text)
            if is_filtered:
                logger.info(f"Content filtered (ad or alert) for VK message {channel_id}:{message_id}")
                # Clean up media files immediately if filtered
                # Note: cleanup_media_files in moderation module is designed to work with the 'pending' dict.
                # Since we filter before adding to pending, we need to manually clean up here.
                # Alternatively, ensure check_content adds to a temporary pending-like structure
                # for cleanup. For now, manual cleanup of downloaded files.
                # Iterate through media_paths and remove files and their parent dirs
                cleaned_dirs = set()
                for file_path in media_paths:
                    if os.path.exists(file_path):
                         try:
                            os.remove(file_path)
                            parent_dir = os.path.dirname(file_path)
                            if parent_dir not in cleaned_dirs and parent_dir.startswith(tempfile.gettempdir()):
                                shutil.rmtree(parent_dir, ignore_errors=True)
                                cleaned_dirs.add(parent_dir)
                         except Exception as e:
                            logger.warning(f"Failed to cleanup VK media file {file_path} after filtering: {e}")
                return # Stop processing if filtered
        except Exception as e:
            logger.error(f"Content filter check failed for VK message {channel_id}:{message_id}: {e}")
            # If filter check fails, proceed with processing (do not filter)

        # Call moderation.send_for_moderation
        # Original client/message object not available for VK, pass None.
        await moderation.send_for_moderation(
            channel_id,
            message_id,
            text,
            None, # client
            None, # original_message
            source_type="vk",
            media_paths=media_paths # Pass the list of paths
        )

    except Exception as e:
        logger.error(f"Error processing VK event {channel_id}:{message_id}: {e}")


async def start_vk_parser():
    """
    Initialize VK parser using User Long Poll and fetch initial history.
    """
    if not config.VK_TOKEN or not config.VK_SOURCE_IDS:
        logger.warning("VK_TOKEN or VK_SOURCE_IDS not configured. VK parser will not start.")
        return

    async with TokenSession(access_token=config.VK_TOKEN) as session:
        api = API(session)

        # Fetch initial history from each source
        logger.info("Fetching initial VK history...")
        for source_id in config.VK_SOURCE_IDS:
            try:
                # wall.get requires owner_id (negative for groups)
                # We stored positive IDs in config, so convert to negative
                vk_owner_id = -source_id # Assuming source_id is positive group ID
                # Fetch a limited number of recent posts (e.g., last 5)
                response = await api.wall.get(owner_id=vk_owner_id, count=5)
                if response and 'items' in response:
                    # Process items in reverse order to simulate chronological appearance
                    for post in reversed(response['items']):
                        # Ensure the post is not an ad or pinned post if not desired
                        # For simplicity, process all retrieved posts for now.
                        channel_id, message_id, text, media_paths, source_type, original_object = await _extract_vk_message_data(session, post)
                        if channel_id and message_id:
                             # Call process message function
                             await _process_vk_message(session, channel_id, message_id, text, media_paths)

            except Exception as e:
                logger.error(f"Error fetching initial history for VK source {source_id}: {e}")

        # Start VK Long Poll listener
        # Use UserLongPoll for parsing user channels
        # mode=2 includes extended info like attachments
        # version=18 is recommended for recent Long Poll features
        lp = UserLongPoll(api, mode=2, version=18)

        logger.info("Starting VK Long Poll listener...")
        try:
            async for event in lp.iter():
                # VK Long Poll events are structured differently from Telethon
                # Need to identify new message events from configured sources
                # Example event structure (with mode=2): [4, message_id, flags, peer_id, timestamp, text, attachments]

                # Check if the event is a new message (type 4)
                # Ensure event has enough elements (at least 7 for type 4 with mode=2)
                if isinstance(event, list) and len(event) >= 7 and event[0] == 4:
                    peer_id = event[3]
                    # Check if the message is from one of the specified VK sources
                    # VK channel/public page IDs are negative. Check if the absolute value
                    # is in our configured source list (which are positive group IDs).
                    # Ensure peer_id is not None and is integer before taking abs()
                    if isinstance(peer_id, int) and abs(peer_id) in config.VK_SOURCE_IDS:
                         # Extract and process the message data
                         channel_id, message_id, text, media_paths, source_type, original_object = await _extract_vk_message_data(session, event)
                         if channel_id and message_id:
                              await _process_vk_message(session, channel_id, message_id, text, media_paths)
                    # else:
                    #     logger.debug(f"Ignorning VK event from unknown peer {peer_id}")
                # else:
                #     logger.debug(f"Ignoring non-message VK event: {event}")

        except Exception as e:
            logger.error(f"Error in VK Long Poll: {e}")


# Example usage (for testing, will be integrated into main app)
# if __name__ == "__main__":
#     asyncio.run(start_vk_parser()) 