import colorsys
import datetime

import aiohttp
import discord
from redbot.core import checks, commands
from redbot.core.i18n import Translator, cog_i18n
from redbot.core.utils.chat_formatting import box, error
from tabulate import tabulate

try:
    from redbot import json  # support of Draper's branch
except ImportError:
    import json


T_ = Translator("MoreUtils", __file__)
_ = lambda s: s

DISCORD_STATUS_NAMES = {
    "none": _("OK"),
    "minor": _("Minor problems"),
    "major": _("Major problems"),
    "critical": _("Critical problems"),
}

_ = T_


# credits to https://stackoverflow.com/questions/14088375/how-can-i-convert-rgb-to-cmyk-and-vice-versa-in-python
def rgb_to_cmyk(r, g, b):
    rgb_scale = 255
    cmyk_scale = 100
    if (r == 0) and (g == 0) and (b == 0):
        # black
        return 0, 0, 0, cmyk_scale

    # rgb [0,255] -> cmy [0,1]
    c = 1 - (r / float(rgb_scale))
    m = 1 - (g / float(rgb_scale))
    y = 1 - (b / float(rgb_scale))

    # extract out k [0,1]
    min_cmy = min(c, m, y)
    c = (c - min_cmy) / (1 - min_cmy)
    m = (m - min_cmy) / (1 - min_cmy)
    y = (y - min_cmy) / (1 - min_cmy)
    k = min_cmy

    # rescale to the range [0,cmyk_scale]
    return c * cmyk_scale, m * cmyk_scale, y * cmyk_scale, k * cmyk_scale


# credits to https://www.geeksforgeeks.org/program-change-rgb-color-model-hsv-color-model/
# logic from http://www.niwa.nu/2013/05/math-behind-colorspace-conversions-rgb-hsl/
def rgb_to_hsv(r, g, b):

    # R, G, B values are divided by 255
    # to change the range from 0..255 to 0..1:
    r, g, b = r / 255.0, g / 255.0, b / 255.0

    # h, s, v = hue, saturation, value
    cmax = max(r, g, b)
    cmin = min(r, g, b)
    diff = cmax - cmin

    # if cmax and cmax are equal then h = 0
    h = (
        0 if cmax == cmin
        else (60 * ((g - b) / diff) + 360) % 360
        if cmax == r else (60 * ((b - r) / diff) + 120) % 360
        if cmax == g else (60 * ((r - g) / diff) + 240) % 360
    )

    # if cmax equal zero
    s = 0 if cmax == 0 else (diff / cmax) * 100

    # compute v
    v = cmax * 100
    return h, s, v


def bool_emojify(bool_var: bool) -> str:
    return "✅" if bool_var else "❌"


@cog_i18n(_)
class MoreUtils(commands.Cog):
    """Some (maybe) useful utils."""

    __version__ = "2.0.19"

    # noinspection PyMissingConstructor
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession(json_serialize=json.dumps)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    @commands.command(name="thetime")
    async def _thetime(self, ctx):
        """Displays the current time of the server."""
        await ctx.send(datetime.datetime.now().strftime(_("%d.%m.%Y %H:%M:%S %Z")))

    @commands.command(aliases=["HEX", "hex", "colour"])
    @checks.bot_has_permissions(embed_links=True)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def color(self, ctx, *, color: discord.Color):
        """Shows some info about provided color."""
        colorrgb = color.to_rgb()
        rgb_coords = [x / 255 for x in colorrgb]
        colorhsv = rgb_to_hsv(*colorrgb)
        h, l, s = colorsys.rgb_to_hls(*rgb_coords)
        colorhls = (h, l * 100, s * 100)
        coloryiq = colorsys.rgb_to_yiq(*rgb_coords)
        colorcmyk = rgb_to_cmyk(*colorrgb)
        async with self.session.get(
            f"https://api.alexflipnote.dev/color/{str(color)[1:]}"
        ) as data:
            color_name = (await data.json()).get("name", "Unknown")
            image_thumbnail = (await data.json()).get("image")
            image_gradient = (await data.json()).get("image_gradient")
        colors_text = (
            "\u200b\n"
            + f"`Name :`  {str(color_name)}\n"
            + f"`RGB  :`  {colorrgb}\n"
            + f"`CMYK :`  {tuple(map(lambda x: isinstance(x, float) and round(x, 2) or x, colorcmyk))}\n"
            + f"`HSV  :`  {tuple(map(lambda x: isinstance(x, float) and round(x, 2) or x, colorhsv))}\n"
            + f"`HLS  :`  {tuple(map(lambda x: isinstance(x, float) and round(x, 2) or x, colorhls))}\n"
            + f"`YIQ  :`  {tuple(map(lambda x: isinstance(x, float) and round(x, 2) or x, coloryiq))}\n"
            + f"`INT  :`  {color.value}\n\u200b"
        )
        em = discord.Embed(
            title=f"🖌️ Details of the color **{str(color)}**:",
            description=colors_text,
            url=f"http://www.color-hex.com/color/{str(color)[1:]}",
            colour=color,
        )
        # CAUTION: That can fail soon
        em.set_thumbnail(url=image_thumbnail)
        em.set_image(url=image_gradient)
        await ctx.send(embed=em)

    @commands.command(pass_context=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def discordstatus(self, ctx):
        """Get current discord status from discordstatus.com"""
        async with ctx.typing():
            try:
                async with self.session.get(
                    "https://srhpyqt94yxb.statuspage.io/api/v2/summary.json"
                ) as data:
                    response = await data.json(loads=json.loads)
            except Exception as e:
                await ctx.send(
                    error(
                        _("Unable to get data from https://discordstatus.com: {}").format(e)
                    )
                )
                return
            status = response["status"]
            status_name = DISCORD_STATUS_NAMES.get(status['indicator'], status['indicator'])
            components = response["components"]
            table = tabulate(
                [(c['name'], c['status'].capitalize().replace('_', ' ')) for c in components]
            )
            await ctx.send(f"{_(status_name)}\n{box(table)}")
