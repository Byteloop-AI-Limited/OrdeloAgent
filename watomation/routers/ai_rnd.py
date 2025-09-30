# %%
from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO

client = genai.Client()

prompt = (
    "Create a picture of a nano banana dish in a fancy restaurant with a Gemini theme"
)

response = client.models.generate_content(
    model="gemini-2.5-flash-image-preview",
    contents=[prompt],
)

# Check for blocked content or other issues before processing
if (
    hasattr(response, "prompt_feedback")
    and response.prompt_feedback
    and hasattr(response.prompt_feedback, "block_reason")
):
    print(f"Content was blocked. Reason: {response.prompt_feedback.block_reason}")
elif response and response.candidates and len(response.candidates) > 0:
    candidate = response.candidates[0]
    if candidate.content and candidate.content.parts:
        for part in candidate.content.parts:
            if part.text is not None:
                print(part.text)
            elif part.inline_data is not None:
                image = Image.open(BytesIO(part.inline_data.data))
                image.save("generated_image.png")
    else:
        print("No content parts found in the response")
else:
    print("No candidates found in the response or response is None")


# %%
# type(BytesIO(part.inline_data.data))
from config import _async_wa_client


async def send_image(image):
    await _async_wa_client.send_image(
        to="447448440754",
        # image=BytesIO(part.inline_data.data),
        image=image,
        mime_type="image/jpeg",
    )


# %%
image_path = "/home/basal/PycharmProjects/OrdeloAgent/data/"
image = Image.open(image_path + "OldFriends.JPG")
image

# %%
prompt = (
    "Create an image of lohith in a baseball outfit hitting a home run."
    "Identify the person using the name on the top of the person.",
    "The image generated should have exact resemblance to the persons in the images provided.",
)

response = client.models.generate_content(
    model="gemini-2.5-flash-image-preview", contents=[prompt, image]
)

# Check for blocked content or other issues before processing
if (
    hasattr(response, "prompt_feedback")
    and response.prompt_feedback
    and hasattr(response.prompt_feedback, "block_reason")
):
    print(f"Content was blocked. Reason: {response.prompt_feedback.block_reason}")
elif response and response.candidates and len(response.candidates) > 0:
    candidate = response.candidates[0]
    if candidate.content and candidate.content.parts:
        for part in candidate.content.parts:
            if part.text is not None:
                print(part.text)
            elif part.inline_data is not None:
                image = Image.open(BytesIO(part.inline_data.data))
                image.save("generated_image.png")
    else:
        print("No content parts found in the response")
else:
    print("No candidates found in the response or response is None")

# %%
image
