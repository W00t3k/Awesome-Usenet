# Majic Movie Selector - Vision & Roadmap

## The Vision
**Majic** = The smartest way to discover, decide, and acquire movies.

While Radarr excels at *getting* movies, it's not great at helping you *decide* what to watch. Majic fills that gap and can eventually handle both.

---

## Current State (v1.0)
- Multi-source recommendations (Oscars, Criterion, RT, Ebert, Usenet)
- User preference learning with vector embeddings
- Radarr integration for downloads
- AI chat assistant
- Release calendar
- Basic authentication

---

## Roadmap

### Phase 1: Smart Discovery (Next)
**Goal:** Make Majic the best at finding movies you'll love

| Feature | Description | Effort |
|---------|-------------|--------|
| **Mood-Based Discovery** | "I'm feeling nostalgic" / "Need something light" / "Want to cry" | Medium |
| **Smart Collections** | Auto-curated: "Hidden 80s Gems", "Director Deep Cuts", "If you liked X" | Medium |
| **Watch History** | Track what you've watched, when, ratings | Small |
| **Streaming Availability** | Show what's on Netflix, Disney+, Prime, etc. (JustWatch API) | Medium |
| **Letterboxd Import** | Import your watchlist and ratings | Small |
| **Trakt Integration** | Sync watch history and lists | Medium |

### Phase 2: Social & Sharing
**Goal:** Movies are better with friends

| Feature | Description | Effort |
|---------|-------------|--------|
| **Watch Parties** | Coordinate movie nights, vote on what to watch | Large |
| **Shared Lists** | Create and share curated lists | Medium |
| **Friend Activity** | See what friends are watching/liking | Medium |
| **Movie Clubs** | Recurring groups with scheduled films | Large |
| **Discussion Threads** | Chat about movies after watching | Medium |

### Phase 3: Direct Acquisition
**Goal:** Reduce/eliminate Radarr dependency for simple setups

| Feature | Description | Effort |
|---------|-------------|--------|
| **Download Client Integration** | Direct SABnzbd/NZBGet support | Large |
| **Quality Profiles** | Simple quality preferences (1080p preferred, 4K if available) | Medium |
| **Auto-Download Rules** | "Auto-grab anything I like over 80 score" | Medium |
| **File Organization** | Basic move/rename on completion | Large |
| **Plex/Jellyfin Notifications** | Notify media servers of new content | Small |

### Phase 4: Intelligence Layer
**Goal:** Majic knows you better than you know yourself

| Feature | Description | Effort |
|---------|-------------|--------|
| **Taste Profile** | Visual breakdown of your preferences | Medium |
| **Viewing Predictions** | "You'll probably watch this Friday night" | Large |
| **Recommendation Explanations** | Deep "why" analysis using LLM | Done ✓ |
| **Discovery Mode** | Intentionally surfaces things outside your comfort zone | Medium |
| **Director/Actor Affinity** | Track who you love, suggest their lesser-known work | Medium |

### Phase 5: Platform Expansion
**Goal:** Majic everywhere

| Feature | Description | Effort |
|---------|-------------|--------|
| **Mobile PWA** | Installable mobile app | Medium |
| **TV Interface** | 10-foot UI for living room | Large |
| **Browser Extension** | "Add to Majic" from IMDb, Letterboxd, etc. | Medium |
| **Voice Control** | "Hey Majic, find me a 90s comedy" | Medium |
| **Widgets** | Desktop/mobile widgets showing today's pick | Small |

---

## Architecture Evolution

### Current
```
[User] → [Majic UI] → [FastAPI] → [Radarr] → [SABnzbd] → [Plex]
```

### Phase 3 (Hybrid)
```
[User] → [Majic UI] → [FastAPI] ─┬→ [Radarr] → [Download Client]
                                 └→ [Direct]  → [Download Client]
```

### Future (Standalone)
```
[User] → [Majic UI] → [FastAPI] → [Download Client] → [Media Server]
                          ↓
                    [Majic Daemon]
                    (monitoring, upgrades)
```

---

## Technical Priorities

### Immediate (This Week)
1. ✅ Logo & branding
2. ✅ Random movie of the day
3. ✅ Simplified filters with decade buttons
4. ✅ "Why this?" explanations
5. [ ] Mood-based discovery UI
6. [ ] Watch history tracking

### Short-term (This Month)
1. [ ] Streaming availability (JustWatch)
2. [ ] Letterboxd import
3. [ ] Smart collections engine
4. [ ] Mobile-responsive improvements
5. [ ] User profiles (multi-user)

### Medium-term (3 Months)
1. [ ] Direct SABnzbd integration
2. [ ] Simple quality profiles
3. [ ] Trakt sync
4. [ ] Social features MVP
5. [ ] PWA support

---

## Design Principles

1. **Magic, not complexity** - Features should feel effortless
2. **Opinionated defaults** - Work great out of the box
3. **Progressive disclosure** - Simple surface, power underneath
4. **Personality** - Majic has character, it's not just a tool
5. **Speed** - Everything should feel instant

---

## Competitive Landscape

| App | Strength | Weakness |
|-----|----------|----------|
| **Radarr** | Acquisition, organization | Discovery, UX |
| **Plex** | Playback, library | Discovery, acquisition |
| **Letterboxd** | Social, reviews | No acquisition |
| **JustWatch** | Streaming availability | No downloads |
| **Trakt** | Tracking, lists | No acquisition |

**Majic's Position:** Best-in-class discovery + smart acquisition + social features

---

## Success Metrics

- **Daily Active Users** - People checking Majic daily
- **Movies Discovered** - Films found through Majic they wouldn't have found otherwise
- **Decision Time** - How fast users go from "I want to watch something" to "watching"
- **Preference Accuracy** - Do users like what we recommend?
- **Downloads Triggered** - Movies acquired through Majic

---

## Next Steps

1. **Mood Discovery** - Add mood-based filtering ("cozy", "thrilling", "mind-bending")
2. **Watch History** - Track watched movies with ratings
3. **Streaming Check** - Show where movies are streaming
4. **Collections** - Auto-generated smart collections
