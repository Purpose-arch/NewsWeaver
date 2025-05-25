import asyncio
from aiovk import API, TokenSession
# DEPRECATED: from aiovk.longpoll import UserLongPoll # No longer using User Long Poll
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

# Словарь для отслеживания последнего ID поста для каждого источника VK
# Формат: {source_id: last_post_id}
last_post_ids = {}


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
    Handles wall post objects.
    """
    channel_id = None
    message_id = None
    text = ""
    media_paths = []
    source_type = "vk"
    original_object = None # Keep track of the original object if needed later

    # Check if it's a wall post item
    if isinstance(vk_object, dict) and 'id' in vk_object and 'owner_id' in vk_object:
        message_id = vk_object.get('id')
        channel_id = vk_object.get('owner_id') # group/page ID (negative)
        text = vk_object.get('text', '')
        original_object = vk_object
        logger.debug(f"Extracted data from wall post: {channel_id}:{message_id}")

        # Wall post attachments are in a list, each item having 'type' and details
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

    # DEPRECATED: Long Poll event handling removed
    # elif isinstance(vk_object, list) and len(vk_object) >= 7 and vk_object[0] == 4: # Long Poll event
    #     message_id = vk_object[1]
    #     channel_id = vk_object[3] # peer_id
    #     text = vk_object[5]
    #     attachments_dict = vk_object[6]
    #     original_object = vk_object
    #     logger.debug(f"Extracted data from LP event: {channel_id}:{message_id}")
    #     # Long Poll attachment processing logic removed


    if channel_id is None or message_id is None:
        # This might happen if the vk_object is neither a wall post nor a recognized LP event (which is now deprecated)
        logger.warning(f"Could not extract essential data from VK object (not a wall post): {vk_object}")
        return None, None, "", [], "vk", None


    return channel_id, message_id, text, media_paths, source_type, original_object


async def _process_vk_message(session, channel_id, message_id, text, media_paths):
    """
    Handle processed VK message data and send to moderation.
    """
    try:
        logger.info(f"Processing VK post from {channel_id} (ID: {message_id}): {text[:100]}... with {len(media_paths)} media files")

        # Apply content filter
        try:
            is_filtered = await content_filter.check_content(text)
            if is_filtered:
                logger.info(f"Content filtered (ad or alert) for VK post {channel_id}:{message_id}")
                # Clean up media files immediately if filtered
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
            logger.error(f"Content filter check failed for VK post {channel_id}:{message_id}: {e}")
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
        logger.error(f"Error processing VK post {channel_id}:{message_id}: {e}")


async def check_for_new_posts(session, api, source_id):
    """
    Checks a single VK source for new posts since the last check.
    """
    vk_owner_id = -source_id # Convert positive group ID to negative owner_id
    try:
        # Fetch latest posts, including extended info for attachments
        response = await api.wall.get(owner_id=vk_owner_id, count=10, extended=1)

        if response and 'items' in response:
            posts = response['items']
            # Filter out non-original posts (like replies, if any, though wall.get usually returns wall posts)
            posts = [post for post in posts if post.get('type') == 'post'] # Explicitly check type

            if not posts:
                logger.debug(f"No original posts found for source {source_id}")
                return

            # Find the highest post ID among the retrieved posts
            latest_retrieved_post_id = max(post.get('id', 0) for post in posts)

            # Get the last processed post ID for this source
            last_processed_post_id = last_post_ids.get(source_id, 0)

            # Filter for new posts (IDs greater than the last processed ID)
            new_posts = [post for post in posts if post.get('id', 0) > last_processed_post_id]

            # Sort new posts by ID to process them chronologically
            new_posts.sort(key=lambda post: post.get('id', 0))

            if new_posts:
                logger.info(f"Found {len(new_posts)} new posts for source {source_id}. Processing...")
                for post in new_posts:
                     channel_id, message_id, text, media_paths, source_type, original_object = await _extract_vk_message_data(session, post)
                     if channel_id and message_id:
                          await _process_vk_message(session, channel_id, message_id, text, media_paths)

                # Update the last processed post ID for this source to the highest ID found
                # This ensures we don't miss posts if multiple arrive between checks
                last_post_ids[source_id] = latest_retrieved_post_id
                logger.info(f"Updated last processed post ID for source {source_id} to {latest_retrieved_post_id}.")
            else:
                logger.debug(f"No new posts found for source {source_id}. Last processed ID: {last_processed_post_id}")

        # Initial population of last_post_ids if this is the first check and no posts were found
        # This prevents reprocessing old posts on subsequent checks if the initial wall was empty
        elif source_id not in last_post_ids:
             if response and 'items' in response and not response['items']:
                 logger.info(f"No posts found for source {source_id} on initial check. Setting last_post_id to 0.")
                 last_post_ids[source_id] = 0
             elif not response:
                  logger.warning(f"Empty or invalid response from wall.get for source {source_id}")

    except Exception as e:
        logger.error(f"Error checking for new posts for VK source {source_id}: {e}")


async def start_vk_parser():
    """
    Initialize VK parser using periodic wall.get checks.
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
                await check_for_new_posts(session, api, source_id)
            except Exception as e:
                logger.error(f"Error fetching initial history for VK source {source_id}: {e}")


# Example usage (for testing, will be integrated into main app)
# if __name__ == "__main__":
#     asyncio.run(start_vk_parser()) 