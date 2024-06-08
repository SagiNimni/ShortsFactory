import asyncio
import threading
from discord.ext import commands
import discord
import requests
from PIL import Image
import os
import time
from secret import discord_bot_token


class DiscordBot(commands.Bot):
    def __init__(self, command_prefix, intents, ready_event, generation_event, closing_event):
        self.client = super().__init__(command_prefix=command_prefix, intents=intents)
        self.directory = os.getcwd()
        self.ready_event = ready_event
        self.generation_event = generation_event
        self.closing_event = closing_event

    @staticmethod
    def split_image(image_file):
        with Image.open(image_file) as im:
            # Get the width and height of the original image
            width, height = im.size
            # Calculate the middle points along the horizontal and vertical axes
            mid_x = width // 2
            mid_y = height // 2
            # Split the image into four equal parts
            top_left = im.crop((0, 0, mid_x, mid_y))
            top_right = im.crop((mid_x, 0, width, mid_y))
            bottom_left = im.crop((0, mid_y, mid_x, height))
            bottom_right = im.crop((mid_x, mid_y, width, height))
            return top_left, top_right, bottom_left, bottom_right

    async def download_image(self, url, filename):
        response = requests.get(url)
        if response.status_code == 200:

            # Define the input and output folder paths
            input_folder = "input"
            output_folder = "output"

            # Check if the output folder exists, and create it if necessary
            if not os.path.exists(output_folder):
                os.makedirs(output_folder)

            # Check if the input folder exists, and create it if necessary
            if not os.path.exists(input_folder):
                os.makedirs(input_folder)
            with open(f"{self.directory}/{input_folder}/{filename}", "wb") as f:
                f.write(response.content)
            print(f"Image downloaded: {filename}")
            input_file = os.path.join(input_folder, filename)

            if "UPSCALED_" not in filename:
                file_prefix = os.path.splitext(filename)[0]
                # Split the image
                top_left, top_right, bottom_left, bottom_right = self.split_image(input_file)
                # Save the output images with dynamic names in the output folder
                top_left.save(os.path.join(output_folder, file_prefix + ".jpg"))
                # top_right.save(os.path.join(output_folder, file_prefix + "_top_right.jpg"))
                # bottom_left.save(os.path.join(output_folder, file_prefix + "_bottom_left.jpg"))
                # bottom_right.save(os.path.join(output_folder, file_prefix + "_bottom_right.jpg"))
            else:
                os.rename(f"{self.directory}/{input_folder}/{filename}", f"{self.directory}/{output_folder}/{filename}")
            # Delete the input file
            os.remove(f"{self.directory}/{input_folder}/{filename}")

            self.generation_event.set()

    async def on_ready(self):
        print("Bot connected")
        self.ready_event.set()

    async def on_message(self, message):
        print(message.content)
        for attachment in message.attachments:
            if "Upscaled by" in message.content:
                file_prefix = 'UPSCALED_'
            else:
                file_prefix = ''
            if attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                try:
                    filename = '_'.join(attachment.filename.split('_')[1: -1])
                    await self.download_image(attachment.url, f"{file_prefix}{filename[:20]}.jpg")
                except Exception as e:
                    print(e)
                    time.sleep(10)
                    continue

        # use Discord message to download images from a channel history, example: "history:50"
        if message.content.startswith("history:"):
            download_qty = int(message.content.split(":")[1])
            channel = message.channel
            async for msg in channel.history(limit=download_qty):
                for attachment in msg.attachments:
                    if "Upscaled by" in message.content:
                        file_prefix = 'UPSCALED_'
                    else:
                        file_prefix = ''
                    if attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                        try:
                            await self.download_image(attachment.url, f"{file_prefix}{attachment.filename}")
                        except Exception as e:
                            print(e)
                            time.sleep(10)
                            continue

    async def close_bot(self):
        await self.close()


def run_discord_bot(ready_event: threading.Event, generation_event: threading.Event, closing_event: threading.Event):
    intents = discord.Intents.all()
    bot = DiscordBot(command_prefix="*", intents=intents, ready_event=ready_event, generation_event=generation_event,
                     closing_event=closing_event)

    def start_bot():
        bot.run(discord_bot_token)

    bot_thread = threading.Thread(target=start_bot)
    bot_thread.start()

    closing_event.wait()
    asyncio.run_coroutine_threadsafe(bot.close_bot(), bot.loop).result()
    bot_thread.join()
