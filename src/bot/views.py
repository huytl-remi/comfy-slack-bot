import os
import uuid
from src.utils.config import load_config
from src.utils.logging_config import logger
from src.utils.exceptions import SDSlackBotError
from src.utils.file_handling import handle_reference_image, cleanup_temp_dir
from src.queue.request_queue import request_queue

config = load_config()

def register_views(app):
    @app.view("image_gen_modal")
    async def handle_submission(ack, body, client, view):
        logger.info("Image generation modal submitted")
        await ack()
        logger.info("Acknowledgement sent, calling process_submission")
        await process_submission(body, client, view, is_remix=False)
        logger.info("process_submission completed for image generation")

    @app.view("remix_modal")
    async def handle_remix_submission(ack, body, client, view):
        logger.info("Remix modal submitted")
        await ack()
        logger.info("Acknowledgement sent, calling process_submission")
        await process_submission(body, client, view, is_remix=True)
        logger.info("process_submission completed for remix")

async def process_submission(body, client, view, is_remix):
    user_id = body["user"]["id"]
    channel_id = body.get("view", {}).get("private_metadata", user_id)
    temp_dir = None
    logger.info(f"Starting process_submission for user {user_id}, is_remix: {is_remix}")
    try:
        logger.info("Parsing input values")
        model_style = view["state"]["values"]["model_style"]["model_select"]["selected_option"]["value"]
        positive_prompt = view["state"]["values"]["positive_prompt"]["prompt_input"]["value"]
        negative_prompt = view["state"]["values"]["negative_prompt"]["neg_prompt_input"]["value"]
        aspect_ratio = view["state"]["values"]["aspect_ratio"]["ratio_select"]["selected_option"]["value"]
        reference_weight = view["state"]["values"]["reference_weight"]["weight_input"]["value"]

        logger.info(f"Parsed values: model_style={model_style}, aspect_ratio={aspect_ratio}, reference_weight={reference_weight}")
        logger.info(f"Positive prompt: {positive_prompt}")
        logger.info(f"Negative prompt: {negative_prompt}")

        width, height = map(int, aspect_ratio.split('x'))
        logger.info(f"Calculated dimensions: {width}x{height}")

        # Handle reference image
        logger.info("Handling reference image")
        if not is_remix:
            reference_image_input = view["state"]["values"]["reference_image"]["file_input"]
            logger.info(f"Reference image input: {reference_image_input}")
            if reference_image_input.get("files"):
                logger.info("Reference image file found, processing...")
                reference_image_path = await handle_reference_image(reference_image_input["files"][0], client)
                temp_dir = os.path.dirname(reference_image_path)
                logger.info(f"Reference image processed, path: {reference_image_path}")
            else:
                logger.info("No reference image uploaded, using default")
                reference_image_path = config['stable_diffusion']['default_reference_path']
        else:
            logger.info("Remix request, using default reference image")
            reference_image_path = config['stable_diffusion']['default_reference_path']

        # Create a unique ID for this request
        request_id = str(uuid.uuid4())
        logger.info(f"Generated request ID: {request_id}")

        # Add request to queue
        logger.info("Adding request to queue")
        queue_position = await request_queue.add_request({
            'id': request_id,
            'user_id': user_id,
            'channel': channel_id,
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
        logger.info(f"Request added to queue at position {queue_position}")

        # Send initial message with queue position
        logger.info("Sending queue position message to user")
        await client.chat_postMessage(
            channel=user_id,
            text=f"Your {'remixed ' if is_remix else ''}image generation request has been queued. You are number {queue_position} in line. "
                 f"Estimated wait time: {request_queue.estimate_wait_time(queue_position)} seconds."
        )
        logger.info("Queue position message sent successfully")

    except SDSlackBotError as e:
        logger.error(f"SDSlackBotError in process_submission: {str(e)}")
        await client.chat_postMessage(channel=user_id, text=f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in process_submission: {str(e)}", exc_info=True)
        await client.chat_postMessage(channel=user_id, text=f"An unexpected error occurred. Please try again later.")

    # Remove any cleanup code from here
    logger.info("process_submission completed")

async def open_image_gen_modal(client, trigger_id, channel_id):
    await client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "image_gen_modal",
            "private_metadata": channel_id,
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
