import os
import asyncio
import uuid
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from src.utils.config import load_config
from src.utils.logging_config import logger
from src.image_generation.sd_wrapper import generate_image
from src.utils.exceptions import SlackAPIError, ImageGenerationError, SDSlackBotError
from src.utils.file_handling import handle_reference_image, cleanup_temp_dir, get_latest_file
from src.queue.request_queue import request_queue
from src.stats.tracker import record_generation_event

config = load_config()
app = AsyncApp(token=config['slack']['bot_token'])

async def send_queue_update(client, user_id, queue_position):
    estimated_time = request_queue.estimate_wait_time(queue_position)
    await client.chat_postMessage(
        channel=user_id,
        text=f"Your image generation request is now at position {queue_position}. "
             f"Estimated wait time: {estimated_time} seconds."
    )

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
        logger.error(f"Error processing image request: {str(e)}")
        await client.chat_postMessage(
            channel=request['user_id'],
            text=f"An error occurred while generating your image: {str(e)}"
        )
    finally:
        await request_queue.complete_current_request()

async def process_queue(client):
    while True:
        request = await request_queue.get_next_request()
        if request is None:
            await asyncio.sleep(1)  # Wait a bit before checking again
            continue

        asyncio.create_task(process_image_request(client, request))

        # Update queue positions for remaining requests
        for i, queued_request in enumerate(request_queue.queue):
            await send_queue_update(client, queued_request['user_id'], i + 1)

@app.command("/generate_image")
async def start_image_generation(ack, body, client):
    await ack()
    try:
        await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "image_gen_modal",
                "private_metadata": body["channel_id"],
                "title": {"type": "plain_text", "text": "Generate Image"},
                "submit": {"type": "plain_text", "text": "Generate"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "model_style",
                        "label": {"type": "plain_text", "text": "Model Style"},
                        "element": {
                            "type": "static_select",
                            "action_id": "model_select",
                            "options": [
                                {"text": {"type": "plain_text", "text": "Realistic"}, "value": "realistic"},
                                {"text": {"type": "plain_text", "text": "Anime"}, "value": "anime"},
                                {"text": {"type": "plain_text", "text": "Korean"}, "value": "korean"}
                            ]
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "positive_prompt",
                        "label": {"type": "plain_text", "text": "Positive Prompt"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "prompt_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Describe what you want in the image. E.g.: A serene landscape with mountains, lake, and sunset"
                            }
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "negative_prompt",
                        "label": {"type": "plain_text", "text": "Negative Prompt (optional)"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "neg_prompt_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Describe what you don't want. E.g.: blurry, low quality, distorted, ugly, deformed"
                            }
                        },
                        "optional": True
                    },
                    {
                        "type": "input",
                        "block_id": "aspect_ratio",
                        "label": {"type": "plain_text", "text": "Aspect Ratio"},
                        "element": {
                            "type": "static_select",
                            "action_id": "ratio_select",
                            "options": [
                                {"text": {"type": "plain_text", "text": "768x1024"}, "value": "768x1024"},
                                {"text": {"type": "plain_text", "text": "1024x768"}, "value": "1024x768"},
                                {"text": {"type": "plain_text", "text": "1024x1024"}, "value": "1024x1024"}
                            ]
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "reference_image",
                        "label": {"type": "plain_text", "text": "Reference Image (optional)"},
                        "element": {"type": "file_input", "action_id": "file_input"},
                        "optional": True
                    },
                    {
                        "type": "input",
                        "block_id": "reference_weight",
                        "label": {"type": "plain_text", "text": "Reference Weight (0-0.58, optional)"},
                        "element": {"type": "plain_text_input", "action_id": "weight_input"},
                        "optional": True
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening modal: {str(e)}")
        raise SlackAPIError(f"Failed to open image generation modal: {str(e)}")

@app.action("regenerate_image")
async def handle_regenerate(ack, body, client):
    await ack()
    user_id = body["user"]["id"]
    request_id = body["actions"][0]["value"].split("_")[1]

    try:
        # Fetch original request details
        original_request = await request_queue.get_request_by_id(request_id)
        if not original_request:
            raise SDSlackBotError("Original request not found")

        # Create a new request with the same parameters
        new_request_id = str(uuid.uuid4())
        new_request = {
            'id': new_request_id,
            'user_id': user_id,
            'channel': original_request['channel'],
            'params': original_request['params']
        }

        # Add new request to queue
        queue_position = await request_queue.add_request(new_request)

        # Send message about queued regeneration
        await client.chat_postMessage(
            channel=user_id,
            text=f"Your image regeneration request has been queued. You are number {queue_position} in line. "
                 f"Estimated wait time: {request_queue.estimate_wait_time(queue_position)} seconds."
        )

    except Exception as e:
        logger.error(f"Error handling regenerate action: {str(e)}")
        await client.chat_postMessage(
            channel=user_id,
            text=f"An error occurred while processing your regeneration request: {str(e)}"
        )

@app.action("remix_image")
async def handle_remix(ack, body, client):
    await ack()
    user_id = body["user"]["id"]
    request_id = body["actions"][0]["value"].split("_")[1]

    try:
        # Fetch original request details
        original_request = await request_queue.get_request_by_id(request_id)
        if not original_request:
            raise SDSlackBotError("Original request not found")

        # Open remix modal
        await open_remix_modal(client, body["trigger_id"], original_request['params'])

    except Exception as e:
        logger.error(f"Error handling remix action: {str(e)}")
        await client.chat_postMessage(
            channel=user_id,
            text=f"An error occurred while processing your remix request: {str(e)}"
        )

@app.view("image_gen_modal")
async def handle_submission(ack, body, client, view):
    await ack()
    user_id = body["user"]["id"]
    # Get the channel ID from the correct location in the payload
    channel_id = body.get("view", {}).get("private_metadata", user_id)
    temp_dir = None
    try:
        model_style = view["state"]["values"]["model_style"]["model_select"]["selected_option"]["value"]
        positive_prompt = view["state"]["values"]["positive_prompt"]["prompt_input"]["value"]
        negative_prompt = view["state"]["values"]["negative_prompt"]["neg_prompt_input"]["value"]
        aspect_ratio = view["state"]["values"]["aspect_ratio"]["ratio_select"]["selected_option"]["value"]
        reference_image_input = view["state"]["values"]["reference_image"]["file_input"]
        reference_weight = view["state"]["values"]["reference_weight"]["weight_input"]["value"]

        width, height = map(int, aspect_ratio.split('x'))

        # Handle reference image
        if "files" in reference_image_input and reference_image_input["files"]:
            reference_image_path = await handle_reference_image(reference_image_input["files"][0], client)
            temp_dir = os.path.dirname(reference_image_path)
        else:
            reference_image_path = config['stable_diffusion']['default_reference_path']

        # Create a unique ID for this request
        request_id = str(uuid.uuid4())

        # Add request to queue
        queue_position = await request_queue.add_request({
            'id': request_id,
            'user_id': user_id,
            'channel': channel_id,  # Use the correctly obtained channel_id
            'params': {
                'positive_prompt': positive_prompt,
                'negative_prompt': negative_prompt or config['image_generation']['default_negative_prompt'],
                'width': width,
                'height': height,
                'reference_image_path': reference_image_path,
                'reference_weight': float(reference_weight) if reference_weight else 0,
                'model_style': model_style
            }
        })

        # Send initial message with queue position
        await client.chat_postMessage(
            channel=user_id,
            text=f"Your image generation request has been queued. You are number {queue_position} in line. "
                 f"Estimated wait time: {request_queue.estimate_wait_time(queue_position)} seconds."
        )

        # Start processing queue if it's not already running
        asyncio.create_task(process_queue(client))

    except SDSlackBotError as e:
        await client.chat_postMessage(channel=user_id, text=f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error handling submission: {str(e)}")
        await client.chat_postMessage(channel=user_id, text=f"An unexpected error occurred. Please try again later.")
    finally:
        if temp_dir:
            await cleanup_temp_dir(temp_dir)

async def open_remix_modal(client, trigger_id, original_params):
    await client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "remix_modal",
            "title": {"type": "plain_text", "text": "Remix Image"},
            "submit": {"type": "plain_text", "text": "Generate"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "model_style",
                    "label": {"type": "plain_text", "text": "Model Style"},
                    "element": {
                        "type": "static_select",
                        "action_id": "model_select",
                        "options": [
                            {"text": {"type": "plain_text", "text": "Realistic"}, "value": "realistic"},
                            {"text": {"type": "plain_text", "text": "Anime"}, "value": "anime"},
                            {"text": {"type": "plain_text", "text": "Korean"}, "value": "korean"}
                        ],
                        "initial_option": {"text": {"type": "plain_text", "text": original_params['model_style'].capitalize()}, "value": original_params['model_style']}
                    }
                },
                {
                    "type": "input",
                    "block_id": "positive_prompt",
                    "label": {"type": "plain_text", "text": "Positive Prompt"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "prompt_input",
                        "initial_value": original_params['positive_prompt']
                    }
                },
                {
                    "type": "input",
                    "block_id": "negative_prompt",
                    "label": {"type": "plain_text", "text": "Negative Prompt (optional)"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "neg_prompt_input",
                        "initial_value": original_params['negative_prompt']
                    },
                    "optional": True
                },
                {
                    "type": "input",
                    "block_id": "aspect_ratio",
                    "label": {"type": "plain_text", "text": "Aspect Ratio"},
                    "element": {
                        "type": "static_select",
                        "action_id": "ratio_select",
                        "options": [
                            {"text": {"type": "plain_text", "text": "768x1024"}, "value": "768x1024"},
                            {"text": {"type": "plain_text", "text": "1024x768"}, "value": "1024x768"},
                            {"text": {"type": "plain_text", "text": "1024x1024"}, "value": "1024x1024"}
                        ],
                        "initial_option": {"text": {"type": "plain_text", "text": f"{original_params['width']}x{original_params['height']}"}, "value": f"{original_params['width']}x{original_params['height']}"}
                    }
                },
                {
                    "type": "input",
                    "block_id": "reference_weight",
                    "label": {"type": "plain_text", "text": "Reference Weight (0-0.58, optional)"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "weight_input",
                        "initial_value": str(original_params['reference_weight'])
                    },
                    "optional": True
                }
            ]
        }
    )

@app.view("remix_modal")
async def handle_remix_submission(ack, body, client, view):
    await ack()
    user_id = body["user"]["id"]
    channel_id = body.get("channel", {}).get("id", user_id)
    try:
        model_style = view["state"]["values"]["model_style"]["model_select"]["selected_option"]["value"]
        positive_prompt = view["state"]["values"]["positive_prompt"]["prompt_input"]["value"]
        negative_prompt = view["state"]["values"]["negative_prompt"]["neg_prompt_input"]["value"]
        aspect_ratio = view["state"]["values"]["aspect_ratio"]["ratio_select"]["selected_option"]["value"]
        reference_weight = view["state"]["values"]["reference_weight"]["weight_input"]["value"]

        width, height = map(int, aspect_ratio.split('x'))

        # Create a unique ID for this request
        request_id = str(uuid.uuid4())

        # Add request to queue
        queue_position = await request_queue.add_request({
            'id': request_id,
            'user_id': user_id,
            'channel': channel_id,
            'params': {
                'positive_prompt': positive_prompt,
                'negative_prompt': negative_prompt or config['image_generation']['default_negative_prompt'],
                'width': width,
                'height': height,
                'reference_image_path': config['stable_diffusion']['default_reference_path'],  # Use default reference image for remix
                'reference_weight': float(reference_weight) if reference_weight else 0,
                'model_style': model_style
            }
        })

        # Send initial message with queue position
        await client.chat_postMessage(
            channel=user_id,
            text=f"Your remixed image generation request has been queued. You are number {queue_position} in line. "
                 f"Estimated wait time: {request_queue.estimate_wait_time(queue_position)} seconds."
        )

        # Start processing queue if it's not already running
        asyncio.create_task(process_queue(client))

    except SDSlackBotError as e:
        await client.chat_postMessage(channel=user_id, text=f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error handling remix submission: {str(e)}")
        await client.chat_postMessage(channel=user_id, text=f"An unexpected error occurred. Please try again later.")

async def start_bot():
    handler = AsyncSocketModeHandler(app, config['slack']['app_token'])
    await handler.start_async()

if __name__ == "__main__":
    import asyncio
    asyncio.run(start_bot())
