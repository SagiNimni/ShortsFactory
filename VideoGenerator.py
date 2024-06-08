from secret import reddit_secret, reddit_id, midjourny_api_key, openai_api_key
from moviepy.editor import ImageClip, concatenate_videoclips
from moviepy.editor import AudioFileClip
from openai import OpenAI
from Midjourney import MidjourneyClient
import praw
import re
import os


class ChatGPTResponseError(Exception):
    pass


class VideoGenerator:
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)' \
                 ' Chrome/120.0.0.0 Safari/537.36'

    def __init__(self, content_path='content'):
        print("Setting up the video generator...")
        self.reddit_client = praw.Reddit(
            client_id=reddit_id,
            client_secret=reddit_secret,
            user_agent=VideoGenerator.user_agent
        )
        self.content_path = content_path
        self.GPT_client = OpenAI(api_key=openai_api_key)

        self.midjourney_client = MidjourneyClient(midjourny_api_key, "session.txt", VideoGenerator.user_agent)
        print("The video generator is set\n############################")

    def generate(self, video_amount, max_length, subreddit):
        print("Retrieving stories from reddit...", end='')
        media = self._mine_narratives_(video_amount, max_length, subreddit)
        print("[SUCCESS]")

        print("Creating Drafts...", end='')
        drafts = self._create_drafts_(media)
        print("[SUCCESS]\n###########################")

        print("Starts video creation...")
        for i, (title, story) in enumerate(drafts, 1):
            print(f"Synthesizing video number {i} ...")
            title = re.sub(r'[<>:"/\\|?*]', '_', title)
            data_path = f"{self.content_path}/{title}"
            if not os.path.exists(data_path):
                os.mkdir(data_path)
                with open(data_path + '/script.txt', 'w+') as f:
                    f.write(story)

            images = self._craft_images_("split this stories into an amount of scenes suitable for "
                                         "a TikTok narration video. for each scene add the narrator"
                                         " line and a prompt suitable for Midjourney6 to describe"
                                         " the scenes in the best way. Avoid writing Punctuation in the image prompt, "
                                         "Also avoid writing names of characters but only descriptions."
                                         " In addition, for each scenes try to"
                                         "predict what part in percentages it would take from the "
                                         " full video time"
                                         " to read this part (make sure that it adds up to 100%)."
                                         " print it in the format of a python list, like this: "
                                         "[('scene1 narrator line', 'scene1 image prompt', percentage as integer),"
                                         " ('scene2 narrator line', 'scene2 image prompt', percentage as integer) ]"
                                         "For example: [ ('In 1949 a weird thing happened in a kindergarten', 'A scary "
                                         "kindergarten', 10) ] make sure the list is formatted in right python syntax"
                                         ,  story)

            narration = ""
            for index, (line, image, timing) in enumerate(images, 1):
                narration += f"{line}. "
                image.save(data_path + f'/{index}-{timing}.jpeg')
            print("Generating narration...", end='')
            speech = self._synthesize_voice_(narration)
            speech.write_to_file(data_path + '/voiceover.aac')
            print("[SUCCESS]")

            print("Stitching the video...", end='')
            self._stitch_videos_(data_path)
            print("[SUCCESS]")
 
            print(f"Video number {i} is completed\n###########################")

    def close_session(self):
        self.midjourney_client.terminate()
        print("The generator session was closed")

    def _mine_narratives_(self, total_media_to_retrieve, max_post_length, subreddits_title):
        results = []
        params = {'limit': 7}

        while len(results) < total_media_to_retrieve:
            batch = list(
                self.reddit_client.subreddit(subreddits_title).top(limit=params['limit'], params=params, time_filter='week'))
            if not batch:
                print("No posts found")
                break

            params = {'limit': params['limit'], 'after': batch[-1].fullname}
            batch = list(filter(lambda post: len(post.selftext.split(" ")) <= max_post_length, batch))
            results.extend(batch)

        return results

    def _create_drafts_(self, media):
        drafts = []

        for post in media:
            story = post.selftext
            response = self.GPT_client.chat.completions.create(
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

    def _craft_images_(self, prompt, script):
        response = self.GPT_client.chat.completions.create(
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
            scenes = response.choices[0].message.content
            narrator_lines, image_prompts, timings = eval('zip(*{0})'.format(scenes.replace('\n', '')))
            print("Crafting Images... ")

            related_images = []
            for i, image_prompt in enumerate(image_prompts, 1):
                print(f"Crafting image number {i}...")
                related_images.append(self.midjourney_client.imagine(image_prompt))

            return list(zip(narrator_lines, related_images, timings))

        else:
            raise ChatGPTResponseError

    def _synthesize_voice_(self, script):
        response = self.GPT_client.audio.speech.create(
            response_format='aac',
            model="tts-1",
            voice="onyx",
            input=script
        )

        return response

    @staticmethod
    def _stitch_videos_(content_path):
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

        final_clip.write_videofile(content_path + '/clip.mp4', codec='libx264', audio_codec='aac', fps=24,
                                   threads=4)
