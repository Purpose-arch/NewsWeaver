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

# Период опроса источников VK в секундах
VK_POLLING_INTERVAL = 60 # Check every 60 seconds

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
    Only processes posts with ID greater than the stored last_post_ids[source_id].
    """
    vk_owner_id = -source_id # Convert positive group ID to negative owner_id
    try:
        # Fetch latest posts, including extended info for attachments
        # Use count=1 to get only the very latest post to update the max ID correctly
        # and then filter based on last_post_ids
        response = await api.wall.get(owner_id=vk_owner_id, count=10, extended=1)

        if response and 'items' in response:
            posts = response['items']
            # Filter out non-original posts
            posts = [post for post in posts if post.get('type') == 'post']

            if not posts:
                logger.debug(f"No original posts found for source {source_id}")
                return

            # Find the highest post ID among the retrieved posts
            # Use max across the potentially 10 retrieved posts to ensure we capture the true latest
            latest_retrieved_post_id = max(post.get('id', 0) for post in posts)

            # Get the last processed post ID for this source
            last_processed_post_id = last_post_ids.get(source_id, 0)

            # Filter for new posts (IDs strictly greater than the last processed ID)
            new_posts = [post for post in posts if post.get('id', 0) > last_processed_post_id]

            # Sort new posts by ID to process them chronologically
            new_posts.sort(key=lambda post: post.get('id', 0))

            if new_posts:
                logger.info(f"Found {len(new_posts)} new posts for source {source_id}. Processing...")
                for post in new_posts:
                     # Only process posts that are actually new based on ID comparison
                     channel_id, message_id, text, media_paths, source_type, original_object = await _extract_vk_message_data(session, post)
                     if channel_id and message_id:
                          await _process_vk_message(session, channel_id, message_id, text, media_paths)

            # Always update the last processed post ID to the latest retrieved ID,
            # even if no new posts were processed in this run. This correctly advances the marker.
            if latest_retrieved_post_id > last_processed_post_id:
                 last_post_ids[source_id] = latest_retrieved_post_id
                 logger.info(f"Updated last processed post ID for source {source_id} to {latest_retrieved_post_id}.")
            else:
                 logger.debug(f"No genuinely new posts found or processed for source {source_id}. Last processed ID remains {last_processed_post_id}")


        # This block is only needed for initial population if wall is empty
        # elif source_id not in last_post_ids:
        #      logger.info(f"No posts found for source {source_id} on initial check. last_post_id will be set to 0 if not already present.")
        #      # last_post_ids.setdefault(source_id, 0) # Ensure it's in the dict even if empty

    except Exception as e:
        logger.error(f"Error checking for new posts for VK source {source_id}: {e}")


async def vk_polling_task(session, api):
    """
    Background task to periodically poll all configured VK sources for new posts.
    """
    while True:
        logger.debug("Running periodic VK polling check...")
        for source_id in config.VK_SOURCE_IDS:
            await check_for_new_posts(session, api, source_id)
            # Optional: Add a small delay between checking sources to avoid burst requests
            await asyncio.sleep(1) # Small delay between sources

        await asyncio.sleep(VK_POLLING_INTERVAL) # Wait before the next full cycle


async def start_vk_parser():
    """
    Initialize VK parser by setting initial last_post_ids and starting the polling task.
    """
    if not config.VK_TOKEN or not config.VK_SOURCE_IDS:
        logger.warning("VK_TOKEN or VK_SOURCE_IDS not configured. VK parser will not start.")
        return

    async with TokenSession(access_token=config.VK_TOKEN) as session:
        api = API(session)

        # --- Initial Setup: Determine the latest post ID for each source without processing ---
        logger.info("Initializing VK parser: Determining last post IDs...")
        for source_id in config.VK_SOURCE_IDS:
             vk_owner_id = -source_id
             try:
                  # Fetch just the single latest post to get its ID
                  response = await api.wall.get(owner_id=vk_owner_id, count=1, extended=1)
                  if response and 'items' in response and response['items']:
                       latest_post = response['items'][0]
                       latest_id = latest_post.get('id', 0)
                       last_post_ids[source_id] = latest_id
                       logger.info(f"Initialized last post ID for source {source_id} to {latest_id}.")
                  else:
                       # If no posts found, initialize with 0
                       last_post_ids[source_id] = 0
                       logger.info(f"No posts found for source {source_id} on initialization. Initialized last post ID to 0.")
             except Exception as e:
                  logger.error(f"Error initializing last post ID for VK source {source_id}: {e}")
                  # On error, also initialize with 0 to attempt processing later if needed
                  last_post_ids[source_id] = 0

        # --- Start the periodic polling task ---
        logger.info(f"Initialization complete. Starting periodic VK polling task (interval: {VK_POLLING_INTERVAL}s)...")
        # Create and start the background task
        asyncio.create_task(vk_polling_task(session, api))
        logger.info("VK polling task started.")

# Example usage (for testing, will be integrated into main app)
# if __name__ == "__main__":
#     asyncio.run(start_vk_parser()) 