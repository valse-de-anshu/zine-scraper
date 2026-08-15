CATEGORIES = [
    {
        "display_name": "TV Series",
        "storage_name": "TV",
        "description": "The standard anime release shown on television or streaming platforms.\n\nIf you are downloading normal weekly episodes, this is almost always the correct option.\nMost anime libraries primarily consist of TV Series.",
        "examples": ["Frieren", "One Piece", "Attack on Titan"],
        "popularity": "★★★★★\nNearly every anime collection contains TV Series.",
        "tip": "Choose this when the episodes are part of Season 1, Season 2, Season 3...\n\nDo not choose this for Movies, OVAs or Specials.",
        "templates": [
            {"display_name": "Season 1", "storage_name": "Season 1", "description": "Used when an anime officially releases its first television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Season 2", "storage_name": "Season 2", "description": "Used when an anime officially releases its second television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Season 3", "storage_name": "Season 3", "description": "Used when an anime officially releases its third television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Season 4", "storage_name": "Season 4", "description": "Used when an anime officially releases its fourth television season.", "tip": "If the official release uses numbered television seasons, select the matching season.\n\nNeed Season 27?\nChoose \"Custom Season...\""},
            {"display_name": "Season 5", "storage_name": "Season 5", "description": "Used when an anime officially releases its fifth television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Season 6", "storage_name": "Season 6", "description": "Used when an anime officially releases its sixth television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Season 7", "storage_name": "Season 7", "description": "Used when an anime officially releases its seventh television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Season 8", "storage_name": "Season 8", "description": "Used when an anime officially releases its eighth television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Season 9", "storage_name": "Season 9", "description": "Used when an anime officially releases its ninth television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Season 10", "storage_name": "Season 10", "description": "Used when an anime officially releases its tenth television season.", "tip": "If the official release uses numbered television seasons, select the matching season."},
            {"display_name": "Custom Season...", "is_custom": True, "description": "Used for unusually numbered seasons.", "tip": "Use this to create folders like Season 27."}
        ]
    },
    {
        "display_name": "Movie",
        "storage_name": "Movies",
        "description": "Animated features produced for theatrical release (the big screen).\n\nThey typically have higher budgets, longer runtimes, and superior production values compared to standard TV episodes.",
        "examples": ["Your Name", "Suzume", "Mugen Train"],
        "popularity": "★★★★☆\nHighly common in anime libraries.",
        "tip": "Choose this for full-length feature films.\n\nDo not choose this for standard TV episodes or direct-to-video OVAs.",
        "templates": [
            {"display_name": "Movie", "storage_name": "Movie", "description": "A standalone movie.", "tip": "Use this for movies like 'Your Name'."},
            {"display_name": "Movie 1", "storage_name": "Movie 1", "description": "The first movie in a franchise.", "tip": "Use this if there are multiple movies in the series."},
            {"display_name": "Movie 2", "storage_name": "Movie 2", "description": "The second movie in a franchise.", "tip": "Use this if there are multiple movies in the series."},
            {"display_name": "Movie 3", "storage_name": "Movie 3", "description": "The third movie in a franchise.", "tip": "Use this if there are multiple movies in the series."},
            {"display_name": "Movie 4", "storage_name": "Movie 4", "description": "The fourth movie in a franchise.", "tip": "Use this if there are multiple movies in the series."},
            {"display_name": "Movie 5", "storage_name": "Movie 5", "description": "The fifth movie in a franchise.", "tip": "Use this if there are multiple movies in the series."},
            {"display_name": "Final Movie", "storage_name": "Final Movie", "description": "The concluding movie in a franchise.", "tip": "Use this for final overarching movies."},
            {"display_name": "Compilation Movie", "storage_name": "Compilation Movie", "description": "A film compiling previous TV episodes.", "tip": "Use for theatrical season recaps."},
            {"display_name": "Recap Movie", "storage_name": "Recap Movie", "description": "A film summarizing the story.", "tip": "Use for quick story summaries."},
            {"display_name": "Custom Movie...", "is_custom": True, "description": "A specific, uniquely named movie.", "tip": "If you want to name the folder the exact movie title, choose this."}
        ]
    },
    {
        "display_name": "OVA",
        "storage_name": "OVAs",
        "description": "Original Video Animation.\nProduced for direct-to-video release (Blu-ray/DVD) without airing on TV or in theaters first.\n\nOften side stories, bonus content, or high-quality standalone episodes.",
        "examples": ["Attack on Titan OVA", "Hellsing Ultimate", "One Punch Man OVA"],
        "popularity": "★★★☆☆\nCollectors usually keep these alongside the main TV series.",
        "tip": "If AniList or MyAnimeList labels this as an OVA, choose OVA.\n\nDo not choose this for regular TV episodes.",
        "templates": [
            {"display_name": "OVA", "storage_name": "OVA", "description": "A standalone OVA.", "tip": "Use this for a single unnumbered OVA."},
            {"display_name": "OVA 1", "storage_name": "OVA 1", "description": "The first OVA in a sequence.", "tip": "Use this if the OVAs are sequentially numbered."},
            {"display_name": "OVA 2", "storage_name": "OVA 2", "description": "The second OVA in a sequence.", "tip": "Use this if the OVAs are sequentially numbered."},
            {"display_name": "OVA 3", "storage_name": "OVA 3", "description": "The third OVA in a sequence.", "tip": "Use this if the OVAs are sequentially numbered."},
            {"display_name": "OVA 4", "storage_name": "OVA 4", "description": "The fourth OVA in a sequence.", "tip": "Use this if the OVAs are sequentially numbered."},
            {"display_name": "OVA 5", "storage_name": "OVA 5", "description": "The fifth OVA in a sequence.", "tip": "Use this if the OVAs are sequentially numbered."},
            {"display_name": "Special OVA", "storage_name": "Special OVA", "description": "An OVA categorized as a special.", "tip": "Use this for event OVAs."},
            {"display_name": "Custom...", "is_custom": True, "description": "A specifically numbered or named OVA.", "tip": "Use this for custom decimal numbering like Episode 10.5."}
        ]
    },
    {
        "display_name": "OAD",
        "storage_name": "OADs",
        "description": "Original Animation DVD.\nA specific sub-type of OVA that is bundled as a physical extra (DVD or Blu-ray) with a limited edition manga volume.",
        "examples": ["Fairy Tail OAD", "That Time I Got Reincarnated as a Slime OAD"],
        "popularity": "★★☆☆☆\nA niche bonus format for source material fans.",
        "tip": "Only choose this if the episode was strictly bundled with a manga volume.\n\nOtherwise, use OVA.",
        "templates": [
            {"display_name": "OAD", "storage_name": "OAD", "description": "A standalone OAD.", "tip": "Use this for a single OAD."},
            {"display_name": "OAD 1", "storage_name": "OAD 1", "description": "The first OAD.", "tip": "Use this if sequentially numbered."},
            {"display_name": "OAD 2", "storage_name": "OAD 2", "description": "The second OAD.", "tip": "Use this if sequentially numbered."},
            {"display_name": "OAD 3", "storage_name": "OAD 3", "description": "The third OAD.", "tip": "Use this if sequentially numbered."},
            {"display_name": "Manga Bundle 1", "storage_name": "Manga Bundle 1", "description": "First manga bundle.", "tip": "Use if tied to a specific manga release volume."},
            {"display_name": "Manga Bundle 2", "storage_name": "Manga Bundle 2", "description": "Second manga bundle.", "tip": "Use if tied to a specific manga release volume."},
            {"display_name": "Custom...", "is_custom": True, "description": "A specifically named OAD.", "tip": "Use this if you need a custom name."}
        ]
    },
    {
        "display_name": "ONA",
        "storage_name": "ONAs",
        "description": "Original Net Animation.\nAnime released directly to the internet (Netflix, YouTube, Crunchyroll) rather than TV.",
        "examples": ["Cyberpunk: Edgerunners", "Devilman Crybaby", "Pluto"],
        "popularity": "★★★★☆\nBecoming highly common in the streaming era.",
        "tip": "Choose this for web-first content.\n\nNote: Media players often treat ONAs identical to TV Series.",
        "templates": [
            {"display_name": "ONA", "storage_name": "ONA", "description": "A standalone ONA.", "tip": "Use for a single unnumbered web release."},
            {"display_name": "ONA 1", "storage_name": "ONA 1", "description": "The first ONA.", "tip": "Use if sequentially numbered."},
            {"display_name": "ONA 2", "storage_name": "ONA 2", "description": "The second ONA.", "tip": "Use if sequentially numbered."},
            {"display_name": "ONA 3", "storage_name": "ONA 3", "description": "The third ONA.", "tip": "Use if sequentially numbered."},
            {"display_name": "Web Season 1", "storage_name": "Web Season 1", "description": "The first web season.", "tip": "Most ONAs follow standard season structures."},
            {"display_name": "Web Season 2", "storage_name": "Web Season 2", "description": "The second web season.", "tip": "Use for follow-up seasons."},
            {"display_name": "Netflix Release", "storage_name": "Netflix Release", "description": "A Netflix original batch.", "tip": "Use for Netflix exclusive drops."},
            {"display_name": "Streaming Release", "storage_name": "Streaming Release", "description": "A general streaming batch.", "tip": "Use for Crunchyroll or other platforms."},
            {"display_name": "Custom...", "is_custom": True, "description": "A specifically named ONA.", "tip": "Use if you need a custom season number."}
        ]
    },
    {
        "display_name": "Special",
        "storage_name": "Specials",
        "description": "A catch-all term for extra episodes that don't fit neatly into the main season.",
        "examples": ["One Piece Specials", "Naruto Shippuden Specials"],
        "popularity": "★★★☆☆\nCommon for long-running series.",
        "tip": "Choose this for side stories or bonus content included on home media releases.",
        "templates": [
            {"display_name": "Special", "storage_name": "Special", "description": "A standalone special.", "tip": "Use if unnumbered."},
            {"display_name": "Special 1", "storage_name": "Special 1", "description": "The first special.", "tip": "Use if sequentially numbered."},
            {"display_name": "Special 2", "storage_name": "Special 2", "description": "The second special.", "tip": "Use if sequentially numbered."},
            {"display_name": "Special 3", "storage_name": "Special 3", "description": "The third special.", "tip": "Use if sequentially numbered."},
            {"display_name": "Anniversary Special", "storage_name": "Anniversary Special", "description": "An anniversary release.", "tip": "Use for franchise anniversaries."},
            {"display_name": "Christmas Special", "storage_name": "Christmas Special", "description": "A holiday-themed special.", "tip": "Use for seasonal specials."},
            {"display_name": "New Year Special", "storage_name": "New Year Special", "description": "A new year special.", "tip": "Use for seasonal specials."},
            {"display_name": "Beach Special", "storage_name": "Beach Special", "description": "A beach episode special.", "tip": "Use for themed specials."},
            {"display_name": "Halloween Special", "storage_name": "Halloween Special", "description": "A holiday-themed special.", "tip": "Use for seasonal specials."},
            {"display_name": "Valentine's Special", "storage_name": "Valentine's Special", "description": "A holiday-themed special.", "tip": "Use for seasonal specials."},
            {"display_name": "Extra Episode", "storage_name": "Extra Episode", "description": "An unnumbered extra episode.", "tip": "Use for unnumbered specials."},
            {"display_name": "Bonus Episode", "storage_name": "Bonus Episode", "description": "A bonus episode.", "tip": "Use for BD/DVD bonuses."},
            {"display_name": "Finale Special", "storage_name": "Finale Special", "description": "A special finale.", "tip": "Use for special endings."},
            {"display_name": "Custom...", "is_custom": True, "description": "A specifically named special.", "tip": "Use if you need to name it after a specific event."}
        ]
    },
    {
        "display_name": "TV Special",
        "storage_name": "TV Specials",
        "description": "A longer, broadcast-special episode aired on television in place of regular programming.",
        "examples": ["Lupin III TV Specials", "One Piece: Episode of East Blue"],
        "popularity": "★★☆☆☆\nSomewhat common for massive franchises.",
        "tip": "Choose this if the special aired on TV natively.\n\nDo not use this for DVD bonus specials.",
        "templates": [
            {"display_name": "TV Special", "storage_name": "TV Special", "description": "A standalone TV special.", "tip": "Use if unnumbered."},
            {"display_name": "TV Special 1", "storage_name": "TV Special 1", "description": "The first TV special.", "tip": "Use if sequentially numbered."},
            {"display_name": "TV Special 2", "storage_name": "TV Special 2", "description": "The second TV special.", "tip": "Use if sequentially numbered."},
            {"display_name": "Broadcast Special", "storage_name": "Broadcast Special", "description": "A special broadcast event.", "tip": "Use for TV block specials."},
            {"display_name": "Anniversary Broadcast", "storage_name": "Anniversary Broadcast", "description": "An anniversary TV special.", "tip": "Use for anniversary events."},
            {"display_name": "Custom...", "is_custom": True, "description": "A specifically named TV special.", "tip": "Use if you need to name it after the broadcast event."}
        ]
    },
    {
        "display_name": "Recap Episode",
        "storage_name": "Recaps",
        "description": "An episode consisting almost entirely of reused footage from previous episodes to summarize the story.",
        "examples": ["Attack on Titan Episode 13.5", "My Hero Academia Recaps"],
        "popularity": "★☆☆☆☆\nMost people skip these.",
        "tip": "Choose this to isolate recap episodes so they don't clutter the main season folder.",
        "templates": [
            {"display_name": "Episode Recap", "storage_name": "Episode Recap", "description": "A generic recap.", "tip": "Use if unnumbered."},
            {"display_name": "Mid Season Recap", "storage_name": "Mid Season Recap", "description": "A mid-season recap.", "tip": "Use for recaps halfway through a season."},
            {"display_name": "End of Season Recap", "storage_name": "End of Season Recap", "description": "An end-of-season recap.", "tip": "Use for season summaries."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom recap number.", "tip": "Use for things like Episode 10.5."}
        ]
    },
    {
        "display_name": "Recap Movie",
        "storage_name": "Recap Movies",
        "description": "A feature-length film consisting of edited footage from a TV series to summarize an entire season.",
        "examples": ["Demon Slayer: Siblings' Bond", "Made in Abyss: Journey's Dawn"],
        "popularity": "★★☆☆☆\nUseful for a quick refresh before a new season.",
        "tip": "Choose this for theatrical or direct-to-video season summaries.",
        "templates": [
            {"display_name": "Recap Movie", "storage_name": "Recap Movie", "description": "A standalone recap movie.", "tip": "Use if unnumbered."},
            {"display_name": "Part 1", "storage_name": "Part 1", "description": "The first part of a recap movie series.", "tip": "Use if split into parts."},
            {"display_name": "Part 2", "storage_name": "Part 2", "description": "The second part of a recap movie series.", "tip": "Use if split into parts."},
            {"display_name": "Final Recap", "storage_name": "Final Recap", "description": "The final recap movie.", "tip": "Use for the concluding recap."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom recap movie.", "tip": "Use if you want to name it exactly."}
        ]
    },
    {
        "display_name": "Bonus Episode",
        "storage_name": "Bonus Episodes",
        "description": "An extra episode bundled with physical media releases or digital purchases.",
        "examples": ["Jujutsu Kaisen Juju Strolls", "Re:Zero Petit"],
        "popularity": "★★☆☆☆\nGreat for dedicated fans.",
        "tip": "Choose this for short, extra content that isn't a full OVA.",
        "templates": [
            {"display_name": "Bonus Episode", "storage_name": "Bonus Episode", "description": "A standalone bonus.", "tip": "Use if unnumbered."},
            {"display_name": "Bonus 1", "storage_name": "Bonus 1", "description": "The first bonus.", "tip": "Use if sequentially numbered."},
            {"display_name": "Bonus 2", "storage_name": "Bonus 2", "description": "The second bonus.", "tip": "Use if sequentially numbered."},
            {"display_name": "Bonus 3", "storage_name": "Bonus 3", "description": "The third bonus.", "tip": "Use if sequentially numbered."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom bonus name.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Blu-ray Bonus",
        "storage_name": "Blu-ray Extras",
        "description": "Video extras specifically included on Blu-ray volume releases.",
        "examples": ["Monogatari Series Commentaries", "Fate/stay night UBW Sunny Day"],
        "popularity": "★☆☆☆☆\nFor archival collections.",
        "tip": "Choose this for BD-exclusive menus, interviews, or short animations.",
        "templates": [
            {"display_name": "Blu-ray Bonus", "storage_name": "Blu-ray Bonus", "description": "A generic BD bonus.", "tip": "Use if unnumbered."},
            {"display_name": "Volume 1 Bonus", "storage_name": "Volume 1 Bonus", "description": "Bonus for Vol 1.", "tip": "Use if split by BD volumes."},
            {"display_name": "Volume 2 Bonus", "storage_name": "Volume 2 Bonus", "description": "Bonus for Vol 2.", "tip": "Use if split by BD volumes."},
            {"display_name": "Volume 3 Bonus", "storage_name": "Volume 3 Bonus", "description": "Bonus for Vol 3.", "tip": "Use if split by BD volumes."},
            {"display_name": "BD Extra", "storage_name": "BD Extra", "description": "A generic BD extra.", "tip": "Use for unnumbered extras."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom extra name.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Short Anime",
        "storage_name": "Shorts",
        "description": "An anime series consisting of episodes that are significantly shorter than the standard 24 minutes (e.g., 2 to 10 minutes).",
        "examples": ["Tsurezure Children", "I Can't Understand What My Husband Is Saying"],
        "popularity": "★★★☆☆\nVery common format for comedies.",
        "tip": "Choose this for officially branded short-form series.",
        "templates": [
            {"display_name": "Short", "storage_name": "Short", "description": "A standalone short.", "tip": "Use if unnumbered."},
            {"display_name": "Short Season 1", "storage_name": "Short Season 1", "description": "The first season.", "tip": "Shorts usually follow standard TV seasons."},
            {"display_name": "Short Season 2", "storage_name": "Short Season 2", "description": "The second season.", "tip": "Shorts usually follow standard TV seasons."},
            {"display_name": "Mini Episodes", "storage_name": "Mini Episodes", "description": "A collection of mini episodes.", "tip": "Use for mini spinoffs."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom season.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Web Short",
        "storage_name": "Web Shorts",
        "description": "Bite-sized promotional animations released on platforms like Twitter or YouTube.",
        "examples": ["Pokemon Generations", "Fate/Grand Order mini-shorts"],
        "popularity": "★★☆☆☆\nNiche promotional material.",
        "tip": "Choose this for tiny, non-broadcast web clips.",
        "templates": [
            {"display_name": "Web Short", "storage_name": "Web Short", "description": "A standalone web short.", "tip": "Use if unnumbered."},
            {"display_name": "Web Short 1", "storage_name": "Web Short 1", "description": "The first short.", "tip": "Use if sequentially numbered."},
            {"display_name": "Web Short 2", "storage_name": "Web Short 2", "description": "The second short.", "tip": "Use if sequentially numbered."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom short name.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Music Video",
        "storage_name": "Music Videos",
        "description": "An officially animated music video (AMV) or promotional song release.",
        "examples": ["Shelter", "YOASOBI - Idol (Official MV)"],
        "popularity": "★★☆☆☆\nFor audio-visual collectors.",
        "tip": "Choose this for standalone music videos.",
        "templates": [
            {"display_name": "Opening Theme", "storage_name": "Opening Theme", "description": "An OP theme.", "tip": "Use for creditless OPs."},
            {"display_name": "Ending Theme", "storage_name": "Ending Theme", "description": "An ED theme.", "tip": "Use for creditless EDs."},
            {"display_name": "Character Song", "storage_name": "Character Song", "description": "A character MV.", "tip": "Use for character-specific songs."},
            {"display_name": "Promotional MV", "storage_name": "Promotional MV", "description": "A promotional MV.", "tip": "Use for standalone MVs."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom MV name.", "tip": "Use to name it exactly after the song."}
        ]
    },
    {
        "display_name": "Promotional Video",
        "storage_name": "PVs",
        "description": "Trailers and promotional videos (PVs) used to market an upcoming series or movie.",
        "examples": ["Chainsaw Man Main PV", "Bleach TYBW Trailer"],
        "popularity": "★☆☆☆☆\nArchival purposes only.",
        "tip": "Choose this to save trailers.",
        "templates": [
            {"display_name": "PV 1", "storage_name": "PV 1", "description": "The first PV.", "tip": "Use if sequentially numbered."},
            {"display_name": "PV 2", "storage_name": "PV 2", "description": "The second PV.", "tip": "Use if sequentially numbered."},
            {"display_name": "Teaser", "storage_name": "Teaser", "description": "A teaser trailer.", "tip": "Use for short early trailers."},
            {"display_name": "Trailer", "storage_name": "Trailer", "description": "A full trailer.", "tip": "Use for main trailers."},
            {"display_name": "Announcement", "storage_name": "Announcement", "description": "An announcement PV.", "tip": "Use for initial reveals."},
            {"display_name": "Character PV", "storage_name": "Character PV", "description": "A character-focused PV.", "tip": "Use for character intros."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom PV name.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Commercial",
        "storage_name": "Commercials",
        "description": "Short animated advertisements (CMs) aired on Japanese television.",
        "examples": ["McDonald's Japan Anime CM", "Cross Road (Z-Kai CM)"],
        "popularity": "★☆☆☆☆\nHighly rare.",
        "tip": "Choose this for 15-30 second ad spots.",
        "templates": [
            {"display_name": "TV Commercial", "storage_name": "TV Commercial", "description": "A broadcast CM.", "tip": "Use for TV ads."},
            {"display_name": "Blu-ray Commercial", "storage_name": "Blu-ray Commercial", "description": "A BD release CM.", "tip": "Use for BD ads."},
            {"display_name": "Promotional Commercial", "storage_name": "Promotional Commercial", "description": "A generic promotional CM.", "tip": "Use for event or brand collabs."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom CM name.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Spin-off",
        "storage_name": "Spin-offs",
        "description": "A new series derived from an existing work, focusing on different characters or a different genre.",
        "examples": ["A Certain Scientific Railgun", "Isekai Quartet"],
        "popularity": "★★★☆☆\nCommon for massive franchises.",
        "tip": "When it's a completely different show in the same universe.",
        "templates": [
            {"display_name": "Spin-off", "storage_name": "Spin-off", "description": "A standalone spin-off.", "tip": "Use if unnumbered."},
            {"display_name": "Spin-off Season 1", "storage_name": "Spin-off Season 1", "description": "The first season of the spin-off.", "tip": "Spin-offs act like standard TV shows."},
            {"display_name": "Spin-off Season 2", "storage_name": "Spin-off Season 2", "description": "The second season of the spin-off.", "tip": "Spin-offs act like standard TV shows."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom season.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Side Story",
        "storage_name": "Side Stories",
        "description": "Ancillary stories occurring parallel to the main plot.",
        "examples": ["Sword Art Online: Extra Edition", "Violet Evergarden Side Story"],
        "popularity": "★★☆☆☆\nFor completionists.",
        "tip": "Choose this for canon stories that aren't part of the main numbered sequence.",
        "templates": [
            {"display_name": "Side Story", "storage_name": "Side Story", "description": "A standalone side story.", "tip": "Use if unnumbered."},
            {"display_name": "Story 1", "storage_name": "Story 1", "description": "The first side story.", "tip": "Use if sequentially numbered."},
            {"display_name": "Story 2", "storage_name": "Story 2", "description": "The second side story.", "tip": "Use if sequentially numbered."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom side story.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Alternative Version",
        "storage_name": "Alternative Versions",
        "description": "A retelling of the same story with different pacing, animation, or outcomes.",
        "examples": ["Fullmetal Alchemist vs FMA: Brotherhood", "Evangelion Rebuilds"],
        "popularity": "★★★☆☆\nUsed for remakes or reboots.",
        "tip": "Choose this for full remakes.",
        "templates": [
            {"display_name": "Alternative Version", "storage_name": "Alternative Version", "description": "An alt version.", "tip": "Use for a standalone alt version."},
            {"display_name": "Director's Cut", "storage_name": "Director's Cut", "description": "A director's cut release.", "tip": "Use for edited re-releases."},
            {"display_name": "Extended Edition", "storage_name": "Extended Edition", "description": "An extended edition.", "tip": "Use for longer edits."},
            {"display_name": "Uncensored Version", "storage_name": "Uncensored Version", "description": "An AT-X uncensored release.", "tip": "Use for uncensored batches."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom season.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Alternative Timeline",
        "storage_name": "Alternative Timelines",
        "description": "Stories set in the same universe but following a different timeline or 'what-if' scenario.",
        "examples": ["Fate/stay night routes", "Steins;Gate 0"],
        "popularity": "★★☆☆☆\nCommon in visual novel adaptations.",
        "tip": "Choose this for branching timeline series.",
        "templates": [
            {"display_name": "Timeline A", "storage_name": "Timeline A", "description": "The first timeline.", "tip": "Use for route A."},
            {"display_name": "Timeline B", "storage_name": "Timeline B", "description": "The second timeline.", "tip": "Use for route B."},
            {"display_name": "Parallel Story", "storage_name": "Parallel Story", "description": "A parallel universe story.", "tip": "Use for what-if scenarios."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom season.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Alternative Setting",
        "storage_name": "Alternative Settings",
        "description": "The same characters placed into a completely different universe or genre.",
        "examples": ["Attack on Titan: Junior High", "Carnival Phantasm"],
        "popularity": "★★☆☆☆\nUsed heavily for comedy spin-offs.",
        "tip": "Choose this for parody or high-school AU adaptations.",
        "templates": [
            {"display_name": "School Version", "storage_name": "School Version", "description": "A high-school AU.", "tip": "Use for school parodies."},
            {"display_name": "Fantasy Version", "storage_name": "Fantasy Version", "description": "A fantasy AU.", "tip": "Use for fantasy spin-offs."},
            {"display_name": "Modern Version", "storage_name": "Modern Version", "description": "A modern AU.", "tip": "Use for modern setting adaptations."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom season.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Compilation Movie",
        "storage_name": "Compilation Movies",
        "description": "A theatrical film combining multiple TV episodes into a single narrative, occasionally adding new scenes.",
        "examples": ["Bocchi the Rock! Re:", "Gurren Lagann The Movie"],
        "popularity": "★★☆☆☆\nGreat for quick rewatches.",
        "tip": "Choose this for theatrical season recaps.",
        "templates": [
            {"display_name": "Part 1", "storage_name": "Part 1", "description": "The first compilation.", "tip": "Use if split into parts."},
            {"display_name": "Part 2", "storage_name": "Part 2", "description": "The second compilation.", "tip": "Use if split into parts."},
            {"display_name": "Part 3", "storage_name": "Part 3", "description": "The third compilation.", "tip": "Use if split into parts."},
            {"display_name": "Complete Collection", "storage_name": "Complete Collection", "description": "The full compilation.", "tip": "Use for a single complete movie."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom movie name.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Crossover",
        "storage_name": "Crossovers",
        "description": "A special event where characters from completely different franchises meet.",
        "examples": ["Lupin III vs. Detective Conan", "Isekai Quartet"],
        "popularity": "★☆☆☆☆\nRare event releases.",
        "tip": "Choose this for massive franchise collaborations.",
        "templates": [
            {"display_name": "Collaboration", "storage_name": "Collaboration", "description": "The first crossover.", "tip": "Use if sequentially numbered."},
            {"display_name": "Collaboration 2", "storage_name": "Collaboration 2", "description": "The second crossover.", "tip": "Use if sequentially numbered."},
            {"display_name": "Event Special", "storage_name": "Event Special", "description": "A crossover event.", "tip": "Use for event specials."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom crossover name.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Prologue",
        "storage_name": "Prologues",
        "description": "An Episode 0 or prequel special released before the main series begins.",
        "examples": ["Fate/stay night UBW Episode 0", "Gundam: The Witch from Mercury Prologue"],
        "popularity": "★★☆☆☆\nHighly important for story context.",
        "tip": "Choose this for Episode 0 releases.",
        "templates": [
            {"display_name": "Prologue", "storage_name": "Prologue", "description": "The prologue episode.", "tip": "Use if unnumbered."},
            {"display_name": "Episode 0", "storage_name": "Episode 0", "description": "The prequel episode.", "tip": "Use to slot chronologically."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom prologue.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Epilogue",
        "storage_name": "Epilogues",
        "description": "A conclusive episode or special taking place after the main story ends.",
        "examples": ["Demon Slayer finale specials", "Code Geass Miraculous Anniversary"],
        "popularity": "★☆☆☆☆\nRare.",
        "tip": "Choose this for 'After Story' content.",
        "templates": [
            {"display_name": "Epilogue", "storage_name": "Epilogue", "description": "The epilogue.", "tip": "Use if unnumbered."},
            {"display_name": "After Story", "storage_name": "After Story", "description": "An after story.", "tip": "Use for post-canon specials."},
            {"display_name": "Final Chapter", "storage_name": "Final Chapter", "description": "The final chapter.", "tip": "Use for the definitive ending."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom epilogue.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Pilot",
        "storage_name": "Pilots",
        "description": "An early test-animation or proof-of-concept episode used to pitch a series.",
        "examples": ["Little Witch Academia (Anime Mirai)", "Death Billiards"],
        "popularity": "★☆☆☆☆\nFor archival collectors.",
        "tip": "Choose this for pre-production test episodes.",
        "templates": [
            {"display_name": "Pilot", "storage_name": "Pilot", "description": "The pilot episode.", "tip": "Use if unnumbered."},
            {"display_name": "Prototype", "storage_name": "Prototype", "description": "A prototype concept.", "tip": "Use for early concepts."},
            {"display_name": "Test Episode", "storage_name": "Test Episode", "description": "A test animation.", "tip": "Use for animation tests."},
            {"display_name": "Custom...", "is_custom": True, "description": "A custom pilot.", "tip": "Use to name it exactly."}
        ]
    },
    {
        "display_name": "Other / Custom",
        "storage_name": "Other",
        "description": "Any release type not covered by standard categories.",
        "examples": ["Season Zero", "Theatrical Cut", "Lost Episodes"],
        "popularity": "★☆☆☆☆\nRarely used.",
        "tip": "The release exists, but it doesn't fit any predefined template.",
        "templates": [
            {"display_name": "Custom Folder...", "is_custom": True, "description": "A completely custom folder name.", "tip": "The entered text becomes the folder name exactly as typed."}
        ]
    }
]
