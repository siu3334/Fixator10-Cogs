import asyncio
import json
from datetime import datetime, timezone
from textwrap import shorten

import aiohttp
from aiohttp.client import request
import discord
from redbot.core import __version__ as redbot_ver
from redbot.core import commands
from redbot.core.config import Config
from redbot.core.i18n import Translator, cog_i18n, get_locale
from redbot.core.utils.chat_formatting import error, inline
from redbot.core.utils.menus import close_menu, menu, DEFAULT_CONTROLS

WEATHER_STATES = {
    "clear-day": "\N{Black Sun with Rays}",
    "clear-night": "\N{Night with Stars}",
    "rain": "\N{Cloud with Rain}",
    "snow": "\N{Cloud with Snow}",
    "sleet": "\N{Snowflake}",
    "wind": "\N{Wind Blowing Face}",
    "fog": "\N{Foggy}",
    "cloudy": "\N{White Sun Behind Cloud}",
    "partly-cloudy-day": "\N{White Sun with Small Cloud}",
    "partly-cloudy-night": "\N{Night with Stars}",
}

# Emoji that will be used for "unknown" strings
UNKNOWN_EMOJI = "❔"

T_ = Translator("Weather", __file__)
_ = lambda s: s

UNITS = {
    "si": {
        "distance": _("km"),
        "intensity": _("mm/h"),
        "accumulation": _("cm"),
        "temp": _("℃"),
        "speed": _("m/s"),
        "pressure": _("hPa"),
    },
}

PRECIP_TYPE_I18N = {"rain": _("Rain"), "snow": _("Snow"), "sleet": _("Sleet")}

_ = T_


@cog_i18n(_)
class Weather(commands.Cog):
    """Weather forecast"""

    __version__ = "2.0.5"

    # noinspection PyMissingConstructor
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xDC5A74E677F24720AA82AD1C237721E7)
        default_guild = {"units": "si"}
        self.config.register_guild(**default_guild)
        self.session = aiohttp.ClientSession(
            json_serialize=json.dumps,
            raise_for_status=True,
        )

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    @commands.command()
    @commands.cooldown(1, 5.0, commands.BucketType.member)
    @commands.bot_has_permissions(embed_links=True)
    async def weather(self, ctx, *, place: str):
        """Shows weather in provided place"""
        api_key = (await self.bot.get_shared_api_tokens("forecastio")).get("secret")
        request_url = f"https://nominatim.openstreetmap.org/search?q={place}&format=jsonv2&addressdetails=1&limit=1"
        headers = {
            "Accept-Language": get_locale(),
            "User-Agent": f"Red-DiscordBot/{redbot_ver} Fixator10-Cogs/Weather/{self.__version__}",
        }
        async with ctx.typing():
            try:
                async with self.session.get(request_url, headers=headers) as r:
                    location = await r.json(loads=json.loads)
            except aiohttp.ClientResponseError as e:
                return await ctx.send(
                    error(
                        _("Cannot find a place {}. OSM returned {}").format(inline(place), e.status)
                    )
                )

            if not location:
                return await ctx.send(error(_("Cannot find a place {}").format(inline(place))))

            location = location[0]
            latitude = location.get("lat", 0)
            longitude = location.get("lon", 0)
            base_url = f"https://dark-sky.p.rapidapi.com/{latitude},{longitude}"
            params = {"lang": "en", "units": "si"}
            headers = {
                "x-rapidapi-key": api_key,
                "x-rapidapi-host": "dark-sky.p.rapidapi.com",
            }
            try:
                async with self.session.get(base_url, params=params, headers=headers) as response:
                    if response.status != 200:
                        return await ctx.send(f"https://http.cat/{response.status}")
                    data = await response.json()
            except asyncio.TimeoutError:
                return await ctx.send(error(_("Unable to get data from forecast.io")))

        by_hour = data["currently"]

        em = discord.Embed(
            title=_("Weather in {}").format(
                shorten(location.get("display_name", UNKNOWN_EMOJI), 244, placeholder="…")
            ),
            description=_("[View on Google Maps](https://www.google.com/maps/place/{},{})").format(
                latitude, longitude
            ),
            color=await ctx.embed_color(),
            timestamp=datetime.utcfromtimestamp(by_hour["time"]),
        )
        em.set_author(name=_("Powered by Dark Sky"), url="https://darksky.net/poweredby/")
        em.add_field(
            name=_("Summary"),
            value="{} {}".format(
                WEATHER_STATES.get(by_hour["icon"], UNKNOWN_EMOJI),
                by_hour["summary"],
            ),
        )
        em.add_field(
            name=_("Temperature"),
            value=f"{by_hour['temperature']}℃ ({by_hour['apparentTemperature']}℃)",
        )
        em.add_field(
            name=_("Air pressure"),
            value="{} {}".format(
                by_hour["pressure"], await self.get_localized_units(ctx, "pressure")
            ),
        )
        em.add_field(name=_("Humidity"), value=f"{int(by_hour['humidity'] * 100)}%")
        em.add_field(
            name=_("Visibility"),
            value="{} {}".format(
                by_hour["visibility"], await self.get_localized_units(ctx, "distance")
            ),
        )
        em.add_field(
            name=_("Wind speed"),
            value="{} {} {}".format(
                await self.wind_bearing_direction(by_hour["windBearing"]),
                by_hour["windSpeed"],
                await self.get_localized_units(ctx, "speed"),
            ),
        )
        em.add_field(name=_("Cloud cover"), value=f"{int(by_hour['cloudCover'] * 100)}%")
        em.add_field(
            name=_("Ozone density"),
            value="{} [DU](https://en.wikipedia.org/wiki/Dobson_unit)".format(by_hour["ozone"]),
        )
        em.add_field(name=_("UV index"), value=by_hour["uvIndex"])
        try:
            preciptype = by_hour["precipType"]
        except KeyError:
            preciptype = None
        em.add_field(
            name=_("Precipitation"),
            value=_("Probability: {}%\n").format(int(by_hour["precipProbability"] * 100))
            + _("Intensity: {} {}").format(
                int(by_hour["precipIntensity"] * 100),
                await self.get_localized_units(ctx, "intensity"),
            )
            + (
                preciptype
                and _("\nType: {}").format(_(PRECIP_TYPE_I18N.get(preciptype, preciptype)))
                or ""
            ),
        )
        close_control = {"❌": close_menu}
        await menu(ctx, [em], close_control)

    @commands.command()
    @commands.cooldown(1, 1, commands.BucketType.default)
    @commands.bot_has_permissions(embed_links=True)
    async def forecast(self, ctx, *, place: str):
        """Shows forecast for provided place for upto next 24 hours."""
        api_key = (await self.bot.get_shared_api_tokens("forecastio")).get("secret")
        request_url = f"https://nominatim.openstreetmap.org/search?q={place}&format=jsonv2&addressdetails=1&limit=1"
        headers = {
            "Accept-Language": get_locale(),
            "User-Agent": f"Red-DiscordBot/{redbot_ver} Fixator10-Cogs/Weather/{self.__version__}",
        }
        async with ctx.typing():
            try:
                async with self.session.get(request_url, headers=headers) as r:
                    location = await r.json(loads=json.loads)
            except aiohttp.ClientResponseError as e:
                return await ctx.send(
                    error(
                        _("Cannot find a place {}. OSM returned {}").format(inline(place), e.status)
                    )
                )

            if not location:
                return await ctx.send(error(_("Cannot find a place {}").format(inline(place))))

            location = location[0]
            latitude = location.get("lat", 0)
            longitude = location.get("lon", 0)
            utc_now = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            base_url = f"https://dark-sky.p.rapidapi.com/{latitude},{longitude},{utc_now}"
            params = {"lang": "en", "units": "si"}
            headers = {
                "x-rapidapi-key": api_key,
                "x-rapidapi-host": "dark-sky.p.rapidapi.com",
            }
            try:
                async with self.session.get(base_url, params=params, headers=headers) as response:
                    if response.status != 200:
                        return await ctx.send(f"https://http.cat/{response.status}")
                    data = await response.json()
            except asyncio.TimeoutError:
                return await ctx.send(error(_("Unable to get data from forecast.io")))

        by_day = data["hourly"]
        pages = []
        for i in range(0, 23):
            data = by_day["data"][i]
            em = discord.Embed(
                title=_("Weather in {}").format(
                    shorten(
                        location.get("display_name", UNKNOWN_EMOJI),
                        244,
                        placeholder="…",
                    )
                ),
                description=f"{by_day['summary']}\n"
                + _("[View on Google Maps](https://www.google.com/maps/place/{},{})").format(
                    latitude,
                    longitude,
                ),
                color=await ctx.embed_color(),
                timestamp=datetime.utcfromtimestamp(data["time"]),
            )
            em.set_author(name=_("Powered by Dark Sky"), url="https://darksky.net/poweredby/")
            em.set_footer(text=_(f"Page {i + 1} of {len(by_day['data'])}"))
            em.add_field(
                name=_("Summary"),
                value="{} {}".format(
                    WEATHER_STATES.get(by_day.get("icon"), UNKNOWN_EMOJI),
                    by_day.get("summary", "No summary for this day"),
                ),
            )
            em.add_field(
                name=_("Temperature"),
                value=f"{data['temperature']} {await self.get_localized_units(ctx, 'temp')}\n"
                + f"({data['apparentTemperature']}{await self.get_localized_units(ctx, 'temp')})",
            )
            em.add_field(
                name=_("Air pressure"),
                value="{} {}".format(
                    data["pressure"], await self.get_localized_units(ctx, "pressure")
                ),
            )
            em.add_field(name=_("Humidity"), value=f"{int(data['humidity'] * 100)}%")
            em.add_field(
                name=_("Visibility"),
                value="{} {}".format(
                    data["visibility"], await self.get_localized_units(ctx, "distance")
                ),
            )
            em.add_field(
                name=_("Wind speed"),
                value="{} {} {}".format(
                    await self.wind_bearing_direction(data["windBearing"]),
                    data["windSpeed"],
                    await self.get_localized_units(ctx, "speed"),
                ),
            )
            em.add_field(name=_("Cloud cover"), value=f"{int(data['cloudCover'] * 100)}%")
            em.add_field(
                name=_("Ozone density"),
                value="{} [DU](https://en.wikipedia.org/wiki/Dobson_unit)".format(data["ozone"]),
            )
            em.add_field(name=_("UV index"), value=data["uvIndex"])
            em.add_field(
                name=_("Precipitation"),
                value=_("Probability: {}%\n").format(int(data["precipProbability"] * 100))
                + _("Intensity: {} {}").format(
                    int(data["precipIntensity"] * 100),
                    await self.get_localized_units(ctx, "intensity"),
                ),
            )
            pages.append(em)
        await menu(ctx, pages, DEFAULT_CONTROLS)

    async def get_localized_units(self, ctx: commands.Context, units_type: str):
        """Get translated contextual units for type"""
        if not ctx.guild:
            return _(
                UNITS.get(await self.config.user(ctx.author).units(), UNITS["si"]).get(
                    units_type, "?"
                )
            )
        current_system = (
            await self.config.user(ctx.author).units() or await self.config.guild(ctx.guild).units()
        )
        return _(UNITS.get(current_system, {}).get(units_type, "?"))

    async def wind_bearing_direction(self, bearing: int):
        """Returns direction based on wind bearing"""
        # https://github.com/pandabubblepants/forecastSMS/blob/e396d978e1ec47b5f3023ce13d5a5f55c57e4f6e/forecastSMS.py#L12-L16
        dirs = [
            _("N"),
            _("NNE"),
            _("NE"),
            _("ENE"),
            _("E"),
            _("ESE"),
            _("SE"),
            _("SSE"),
            _("S"),
            _("SSW"),
            _("SW"),
            _("WSW"),
            _("W"),
            _("WNW"),
            _("NW"),
            _("NNW"),
        ]
        return dirs[int((bearing / 22.5) + 0.5) % 16]
