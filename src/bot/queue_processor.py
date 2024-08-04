import asyncio
import os
from src.utils.logging_config import logger
from src.utils.exceptions import SDSlackBotError
from src.queue.request_queue import request_queue
from src.image_generation.sd_wrapper import generate_image
from src.utils.file_handling import get_latest_file

async def process_queue(client):
    while True:
        request = await request_queue.get_next_request()
        if request is None:
            await asyncio.sleep(1)  # Wait a bit before checking again
            continue

        await process_image_request(client, request)

        # Update queue positions for remaining requests
        for i, queued_request in enumerate(request_queue.queue):
            await send_queue_update(client, queued_request['user_id'], i + 1)

async def process_image_request(client, request):
    try:
        output_path = await generate_image(**request['params'])

        # Get the directory and filename prefix
        output_dir = os.path.dirname(output_path)
        filename_prefix = os.path.basename(output_path).split('.')[0]  # Remove the extension

        # Get the actual file path
        actual_file_path = get_latest_file(output_dir, filename_prefix)

        # Prepare the message text with metadata
        message_text = (
            f"<@{request['user_id']}> Here's your generated image!\n"
            f"Positive prompt: {request['params']['positive_prompt']}\n"
            f"Negative prompt: {request['params']['negative_prompt']}\n"
            f"Model: {request['params']['model_style']}\n"
            f"Aspect ratio: {request['params']['width']}x{request['params']['height']}"
        )

        # Prepare blocks for buttons
        button_blocks = [
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Regenerate"},
                        "value": f"regenerate_{request['id']}",
                        "action_id": "regenerate_image"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Remix"},
                        "value": f"remix_{request['id']}",
                        "action_id": "remix_image"
                    }
                ]
            }
        ]

        # Open a DM channel with the user
        dm_channel = await client.conversations_open(users=request['user_id'])
        dm_channel_id = dm_channel['channel']['id']

        # Upload image file to DM with all information
        dm_upload_result = await client.files_upload_v2(
            channel=dm_channel_id,
            file=actual_file_path,
            initial_comment=message_text
        )

        # Send the button message to DM
        await client.chat_postMessage(
            channel=dm_channel_id,
            text="Actions:",
            blocks=button_blocks
        )

        # Send to original channel if different from DM and is a valid channel ID
        original_channel = request.get('channel')
        if original_channel and original_channel != dm_channel_id and original_channel.startswith(('C', 'G')):
            try:
                # Upload the file to the original channel
                await client.files_upload_v2(
                    channel=original_channel,
                    file=actual_file_path,
                    initial_comment=message_text
                )

                # Send the button message to the original channel
                await client.chat_postMessage(
                    channel=original_channel,
                    text="Actions:",
                    blocks=button_blocks
                )
            except Exception as channel_upload_error:
                logger.error(f"Failed to upload file to channel {original_channel}: {str(channel_upload_error)}")
                # If file upload fails, send a message with the file link instead
                file_link = dm_upload_result['file']['permalink']
                await client.chat_postMessage(
                    channel=original_channel,
                    text=f"{message_text}\n\nYou can view the image here: {file_link}"
                )
                await client.chat_postMessage(
                    channel=original_channel,
                    text="Actions:",
                    blocks=button_blocks
                )
        elif original_channel and original_channel != dm_channel_id:
            logger.warning(f"Invalid channel ID: {original_channel}. Skipping channel upload.")

    except Exception as e:
        logger.error(f"Error processing image request: {str(e)}", exc_info=True)
        await client.chat_postMessage(
            channel=request['user_id'],
            text=f"An error occurred while generating your image: {str(e)}"
        )
    finally:
        await request_queue.complete_current_request()

async def send_queue_update(client, user_id, queue_position):
    estimated_time = request_queue.estimate_wait_time(queue_position)
    await client.chat_postMessage(
        channel=user_id,
        text=f"Your image generation request is now at position {queue_position}. "
             f"Estimated wait time: {estimated_time} seconds."
    )

async def start_queue_processing(client):
    asyncio.create_task(process_queue(client))
