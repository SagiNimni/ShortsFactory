from moviepy.editor import ImageClip, concatenate_videoclips
from moviepy.editor import AudioFileClip
from functools import partial
from operator import is_not
from openai import OpenAI
from PIL import Image
import openai
import praw
import re
import requests
import io
import os


class ChatGPTResponseError(Exception):
    pass


def mine_narratives(reddit: praw.Reddit, total_media_to_retrieve, max_post_length, subreddits_title):
    results = []
    params = {'limit': 7}

    while len(results) < total_media_to_retrieve:
        batch = list(reddit.subreddit(subreddits_title).top(limit=params['limit'], params=params, time_filter='week'))
        if not batch:
            print("No posts found")
            break

        params = {'limit': params['limit'], 'after': batch[-1].fullname}
        batch = list(filter(lambda post: len(post.selftext.split(" ")) <= max_post_length, batch))
        results.extend(batch)

    return results


def create_drafts(gpt: OpenAI, media):
    def preprocess_text(text):
        return re.sub(r'\n|\s+|[\*\\]|^\d+s\+', ' ', text).strip()

    drafts = []

    for post in media:
        story = post.selftext
        response = gpt.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": "I have a certain script: '{0}'"
                               "Generate a very short title for a YouTube Short based on the script."
                               " Make it similar to the examples below style in writing. "
                               "Examples: - Scary things hidden in normal photos Part#28 -"
                               " This is the scariest video on the internet".format(story),
                }
            ],
            model="gpt-4",
        )
        drafts.append((response.choices[0].message.content, story))

    return drafts


def craft_images(gpt: OpenAI, prompt, script):
    def regex(text):
        sentence = re.search(r'"([^"]*)"', text)
        percentage = re.search(r'\(([^)]+)\)', text)

        if sentence and percentage:
            return sentence.group(1), percentage.group(1)
        else:
            return None

    response = gpt.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "system", "content": prompt},
                  {"role": "user", 'content': script}],
        temperature=1,
        max_tokens=1024,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0
    )

    if response.choices[0].message is not None:
        images_prompts, theme = response.choices[0].message.content.split('///')
        images_prompts = images_prompts.split('\n')
        images_prompts = list(map(lambda sentence: regex(sentence), images_prompts))
        images_prompts = list(filter(partial(is_not, None), images_prompts))
        images_prompts, timings = zip(*images_prompts)
        timings = list(map(lambda t: t.replace('%', ''), timings))
        print("Crafting Images... ")

        related_images = []
        for i, image_prompt in enumerate(images_prompts, 1):
            print(f"Crafting image number {i}...")

            try:
                response = gpt.images.generate(prompt=f"Here is the theme of the story: {theme}.\n "
                                                      f"Here is the scene to illustrate: {image_prompt}",
                                               size="1024x1792", model="dall-e-3", quality="standard", n=1)
                data = requests.get(response.data[0].url).content
                related_images.append(Image.open(io.BytesIO(data)))

            except openai.BadRequestError:
                success = False
                while not success:
                    try:
                        print(f'The image prompt: "{image_prompt}" is not passing the NSFW!')
                        image_prompt = input("Please enter a modified version: ")
                        response = gpt.images.generate(prompt=image_prompt, size="1024x1792",
                                                       model="dall-e-3", quality="standard", n=1)
                        data = requests.get(response.data[0].url).content
                        related_images.append(Image.open(io.BytesIO(data)))
                        success = True
                    except openai.BadRequestError:
                        pass

        return list(zip(related_images, timings))
    else:
        raise ChatGPTResponseError


def synthesize_voice(gpt: OpenAI, script):
    response = gpt.audio.speech.create(
        response_format='aac',
        model="tts-1",
        voice="onyx",
        input=script
    )

    return response


def stitch_videos(content_path):
    def sort_key(filename):
        number = int(filename.split('-')[0])
        return number

    image_files = [f for f in os.listdir(content_path) if f.endswith('jpeg')]
    image_files = sorted(image_files, key=sort_key)
    percentages = list(map(lambda name: name.split('-')[1].split('.')[0], image_files))
    image_files = list(map(lambda f: os.path.join(content_path, f), image_files))

    audio_clip = AudioFileClip(content_path + '/voiceover.aac')

    video_clips = []
    for i, image_path in enumerate(image_files):
        duration = int(percentages[i]) / 100 * audio_clip.duration
        img_clip = ImageClip(image_path, duration=duration)
        video_clips.append(img_clip)

    concatenated_clips = concatenate_videoclips(video_clips, method='compose')
    final_clip = concatenated_clips.set_audio(audio_clip)

    final_clip.write_videofile(content_path + '/clip.mp4', codec='libx264', audio_codec='aac', fps=24, threads=4)


if __name__ == '__main__':

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
                 " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    reddit_client = praw.Reddit(
        client_id=reddit_id,
        client_secret=reddit_secret,
        user_agent=user_agent
    )

    GPT_client = OpenAI(api_key=openai_api_key)

    media = mine_narratives(reddit_client, 5, 500, 'UnresolvedMysteries')

    drafts = create_drafts(GPT_client, media)
    for title, story in drafts:
        title = re.sub(r'[<>:"/\\|?*]', '_', title)
        data_path = f"content/{title}"
        if not os.path.exists(data_path):
            os.mkdir(data_path)
            with open(data_path + '/script.txt', 'w+') as f:
                f.write(story)

        images = craft_images(GPT_client, "Create a list of key narrative elements suitable for a DALL-E image "
                                          "generator, each accompanied by a percentage that represents its relative"
                                          "  weight or importance in the overall narrative. Ensure that the total of "
                                          "the percentages equals 100%. The narrative elements should be concise, "
                                          "descriptive, and specifically crafted for generating images with DALL-E."
                                          " They must be appropriate for a video script and must not contain any NSFW"
                                          " content. The percentages should reflect the narrative weight of each "
                                          "element and should not indicate the sequence of events in the video. "
                                          "Format the output as an index, followed by the narrative element"
                                          " in quotes, and then the percentage in parentheses. "
                                          " from the story. At the end of this write a description of the theme"
                                          " and characters including looks and clothing with name for each character"
                                          " (make it up if there is no name in the story). separate the two parts with "
                                          "'///' sign", story)

        for index, (image, timing) in enumerate(images, 1):
            image.save(data_path + f'/{index}-{timing}.jpeg')

        speech = synthesize_voice(GPT_client, story)
        speech.write_to_file(data_path + '/voiceover.aac')
        stitch_videos("content/_My Boyfriend's Creepy Family Secret_")

        break
