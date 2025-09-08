import os
import json
import asyncio
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime


class CameraBot(commands.Bot):
    SETTINGS_FILE = "camera_settings.json"

    def __init__(self, command_prefix, intents):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.c_prefix = command_prefix
        self.settings = {}
        self.load_settings()
        self.photo_loop_task = None

    # Settings
    def load_settings(self):
        try:
            with open(self.SETTINGS_FILE, "r") as file:
                self.settings = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.settings = {
                "channel_name": None,
                "interval_minutes": 5,
                "delete_after_upload": False,
                "special_windows": [],  # list of dicts like {"start": "16:30", "end": "16:35", "interval": 30}
            }

    def save_settings(self, **kwargs):
        self.settings.update({k: v for k, v in kwargs.items() if v is not None})
        with open(self.SETTINGS_FILE, "w") as file:
            json.dump(self.settings, file)

    # Camera integration
    async def take_photo(self, prefix="photo", width=640, height=480):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{prefix}_{timestamp}.jpg"
        
        cmd = f"libcamera-still -o {filename} --width {width} --height {height} -n"
        exit_code = os.system(cmd)
        if exit_code != 0:
            raise RuntimeError("Failed to capture photo")
        return filename

    async def upload_photo(self, channel, filename):
        with open(filename, "rb") as file:
            await channel.send(file=discord.File(file, filename))
        if self.settings.get("delete_after_upload"):
            os.remove(filename)

    # Background tasks
    @tasks.loop(minutes=1)
    async def photo_loop(self):
        await self.wait_until_ready()
        now = datetime.now()
        channel_name = self.settings.get("channel_name")

        if not channel_name:
            return

        # Find the channel
        for guild in self.guilds:
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if not channel:
                continue

            # Special window check
            for window in self.settings.get("special_windows", []):
                start = datetime.strptime(window["start"], "%H:%M").time()
                end = datetime.strptime(window["end"], "%H:%M").time()
                interval = window["interval"]

                if start <= now.time() <= end:
                    if now.second % interval == 0:  # crude check
                        filename = await self.take_photo("special")
                        await self.upload_photo(channel, filename)
                    return

            # Normal interval check
            if now.minute % self.settings.get("interval_minutes", 5) == 0 and now.second == 0:
                filename =  await self.take_photo("interval")
                await self.upload_photo(channel, filename)

    async def on_ready(self):
        print(f"Bot connected as {self.user}")
        if not self.photo_loop.is_running():
            self.photo_loop.start()


def main():
    load_dotenv()
    TOKEN = os.getenv("DISCORD_TOKEN")

    intents = discord.Intents.default()
    intents.messages = True
    intents.guilds = True
    bot = CameraBot(command_prefix="$", intents=intents)

    # Commands
    @bot.command(name="setchannel")
    async def set_channel(ctx, *, channel_name: str):
        bot.save_settings(channel_name=channel_name)
        await ctx.send(f"Photo channel set to #{channel_name}")

    @bot.command(name="snap")
    async def snap(ctx):
        channel_name = bot.settings.get("channel_name")
        if not channel_name:
            await ctx.send("No channel set. Use $setchannel first.")
            return
        channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
        filename = await bot.take_photo("snap")
        await bot.upload_photo(channel, filename)

    @bot.command(name="setinterval")
    async def set_interval(ctx, minutes: int):
        if minutes < 1:
            await ctx.send("Interval must be at least 1 minute.")
            return
        bot.save_settings(interval_minutes=minutes)
        await ctx.send(f"Interval set to every {minutes} minutes.")

    @bot.command(name="addwindow")
    async def add_window(ctx, start: str, end: str, interval: int):
        """Add a special photo window: HH:MM HH:MM interval_seconds"""
        windows = bot.settings.get("special_windows", [])
        windows.append({"start": start, "end": end, "interval": interval})
        bot.save_settings(special_windows=windows)
        await ctx.send(f"Special window added: {start}-{end} every {interval}s.")

    @bot.command(name="clearwindows")
    async def clear_windows(ctx):
        bot.save_settings(special_windows=[])
        await ctx.send("All special windows cleared.")

    @bot.command(name="autodelete")
    async def set_autodelete(ctx, value: str):
        val = value.lower() in ["yes", "true", "1", "on"]
        bot.save_settings(delete_after_upload=val)
        await ctx.send(f"Auto-delete after upload {'enabled' if val else 'disabled'}.")

    bot.run(TOKEN)


if __name__ == "__main__":
    main()
