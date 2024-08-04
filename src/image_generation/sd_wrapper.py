import sys
import os
import time
import asyncio
import torch
from PIL import Image
from pathlib import Path
from typing import Optional
from src.utils.config import load_config
from src.utils.logging_config import logger
from src.utils.exceptions import ImageGenerationError

config = load_config()
sys.path.append(config['stable_diffusion']['comfyui_path'])

# Import ComfyUI modules
from nodes import (
    CLIPTextEncode,
    SaveImage,
    NODE_CLASS_MAPPINGS,
    VAEDecode,
    KSampler,
    CheckpointLoaderSimple,
    EmptyLatentImage,
)

def import_custom_nodes() -> None:
    """Find all custom nodes in the custom_nodes folder and add those node objects to NODE_CLASS_MAPPINGS

    This function sets up a new asyncio event loop, initializes the PromptServer,
    creates a PromptQueue, and initializes the custom nodes.
    """
    import asyncio
    import execution
    from nodes import init_builtin_extra_nodes, init_external_custom_nodes
    import server

    # Creating a new event loop and setting it as the default loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Creating an instance of PromptServer with the loop
    server_instance = server.PromptServer(loop)
    execution.PromptQueue(server_instance)

    # Initializing custom nodes
    init_builtin_extra_nodes()
    init_external_custom_nodes()

def load_model(model_style: str):
    model_path = config['stable_diffusion']['models'].get(model_style)
    if not model_path:
        raise ImageGenerationError(f"Invalid model style: {model_style}")

    checkpointloadersimple = CheckpointLoaderSimple()
    return checkpointloadersimple.load_checkpoint(ckpt_name=model_path)

async def generate_image(
    positive_prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    reference_image_path: str,
    reference_weight: float,
    model_style: str,
    seed: Optional[int] = None
) -> str:
    logger.info(f"Starting image generation with parameters: {locals()}")

    try:
        # Run the CPU-bound operations in a thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _generate_image_sync,
                                            positive_prompt, negative_prompt, width, height,
                                            reference_image_path, reference_weight, model_style, seed)
        logger.info("Image generation completed successfully")
        return result
    except FileNotFoundError as e:
        logger.error(f"Reference image not found: {str(e)}")
        raise ImageGenerationError(f"Reference image not found: {str(e)}")
    except Exception as e:
        logger.error(f"Error during image generation: {str(e)}", exc_info=True)
        raise ImageGenerationError(f"Failed to generate image: {str(e)}")

def _generate_image_sync(
    positive_prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    reference_image_path: str,
    reference_weight: float,
    model_style: str,
    seed: Optional[int] = None
) -> str:
    import_custom_nodes()
    with torch.inference_mode():
        # Load model
        model = load_model(model_style)

        # Load reference image
        logger.info(f"Attempting to load reference image from: {reference_image_path}")

        if not os.path.exists(reference_image_path):
            raise FileNotFoundError(f"Reference image file does not exist: {reference_image_path}")

        # Verify the image again before loading
        try:
            with Image.open(reference_image_path) as img:
                img.verify()
            logger.info(f"Reference image verified successfully: {reference_image_path}")
        except Exception as e:
            logger.error(f"Failed to verify reference image: {str(e)}")
            # Try to log some information about the file
            try:
                file_size = os.path.getsize(reference_image_path)
                logger.info(f"File size: {file_size} bytes")
                with open(reference_image_path, 'rb') as f:
                    first_bytes = f.read(100)
                logger.info(f"First 100 bytes of the file: {first_bytes}")
            except Exception as debug_e:
                logger.error(f"Error while debugging file: {str(debug_e)}")
            raise FileNotFoundError(f"Reference image file is corrupted: {reference_image_path}")

        loadimagefrompath = NODE_CLASS_MAPPINGS["LoadImageFromPath"]()
        loadimagefrompath_result = loadimagefrompath.load_image(image=reference_image_path)

        # Encode prompts
        cliptextencode = CLIPTextEncode()
        positive_conditioning = cliptextencode.encode(text=positive_prompt, clip=model[1])
        negative_conditioning = cliptextencode.encode(text=negative_prompt, clip=model[1])

        # Generate empty latent image
        emptylatentimage = EmptyLatentImage()
        latent_image = emptylatentimage.generate(width=width, height=height, batch_size=1)

        # Apply IP-Adapter
        ipadapterunifiedloader = NODE_CLASS_MAPPINGS["IPAdapterUnifiedLoader"]()
        ipadapter_model = ipadapterunifiedloader.load_models(
            preset="PLUS (high strength)",
            model=model[0],
        )

        ipadapteradvanced = NODE_CLASS_MAPPINGS["IPAdapterAdvanced"]()
        ipadapter_result = ipadapteradvanced.apply_ipadapter(
            weight=reference_weight,
            weight_type="style transfer",
            combine_embeds="concat",
            start_at=0,
            end_at=1,
            embeds_scaling="V only",
            model=ipadapter_model[0],
            ipadapter=ipadapter_model[1],
            image=loadimagefrompath_result[0],
        )

        # Apply perturbed attention guidance
        perturbedattentionguidance = NODE_CLASS_MAPPINGS["PerturbedAttentionGuidance"]()
        pag_result = perturbedattentionguidance.patch(scale=3, model=ipadapter_result[0])

        # Apply automatic CFG
        automatic_cfg = NODE_CLASS_MAPPINGS["Automatic CFG"]()
        cfg_result = automatic_cfg.patch(hard_mode=True, boost=True, model=pag_result[0])

        # Sample
        ksampler = KSampler()
        sampler_result = ksampler.sample(
            seed=seed if seed is not None else torch.randint(0, 2**32 - 1, (1,)).item(),
            steps=15,
            cfg=2.5,
            sampler_name="dpmpp_3m_sde_gpu",
            scheduler="exponential",
            denoise=1,
            model=cfg_result[0],
            positive=positive_conditioning[0],
            negative=negative_conditioning[0],
            latent_image=latent_image[0],
        )

        # Decode VAE
        vaedecode = VAEDecode()
        decoded_image = vaedecode.decode(samples=sampler_result[0], vae=model[2])

        # Save image
        saveimage = SaveImage()
        output_path = os.path.join(config['stable_diffusion']['output_path'], f"ComfyUI_{model_style}_{os.urandom(4).hex()}.png")
        saveimage.save_images(filename_prefix=output_path, images=decoded_image[0])

        logger.info(f"Image generation completed. Saved as {output_path}")
        return output_path
