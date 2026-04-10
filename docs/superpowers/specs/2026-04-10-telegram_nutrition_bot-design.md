# Telegram Nutrition Bot Design

## Goal

Build a dedicated private Telegram nutrition bot that accepts meal photos in a direct message, estimates calories and nutrient composition, asks the user to choose from `2-3` candidates when confidence is not decisive, accepts both button and free-text corrections, and replies in text only.

The bot should get smarter from correction history and personal defaults without mutating canonical nutrition facts. Hermes should remain the Telegram front end. A separate nutrition service should own nutrition truth, adaptive ranking, and the meal log.

## Scope

This design covers:

- a dedicated Telegram bot and Hermes profile for nutrition logging
- DM photo intake only
- packaged foods plus plated meals
- a separate nutrition service backed by Postgres
- one-way import of the current `shopping_bot` local-file food-label data into the nutrition service
- candidate selection, correction handling, and adaptive ranking

This design does not cover:

- Telegram channel-post support
- group-chat workflows
- voice replies or audio output
- direct write-through into Garmin or another health system
- barcode-first scanning as a separate mode

## Current State

Hermes already has useful seams for this feature:

- [`gateway/platforms/telegram.py`](/Users/dewoller/code/personal/hermes-agent/gateway/platforms/telegram.py) already receives Telegram photos, caches them locally, and supports inline callback buttons.
- [`gateway/run.py`](/Users/dewoller/code/personal/hermes-agent/gateway/run.py) already enriches inbound image messages through the vision path before the agent responds.

Those seams make Hermes a good Telegram shell for this feature, but not a good home for nutrition state. The current `shopping_bot` food-label data lives in a local file inside another repo or process. That is useful as seed data, but it is the wrong long-term runtime dependency for a production nutrition bot.

There is also one Telegram constraint worth making explicit: the current adapter handles normal message updates cleanly, but this v1 should use a direct bot chat rather than a private channel. That keeps the product aligned with the existing adapter path instead of adding channel-post support before the core nutrition loop exists.

## Recommended Architecture

Use a dedicated Telegram bot and dedicated Hermes profile as the chat front end. Put all nutrition state and decision-making behind a separate nutrition service with Postgres.

### Components

#### Hermes Nutrition Bot

Hermes is responsible for:

- receiving DM photos and captions
- caching uploaded images
- forwarding image-analysis requests to the nutrition service
- presenting ranked candidates in Telegram
- accepting inline-button picks and free-text corrections
- replying with short logged summaries in text

Hermes is not responsible for:

- owning canonical food data
- calculating nutrition truth directly
- storing meal history as primary state
- learning nutrition facts from user corrections

That boundary keeps the bot simple and keeps nutrition logic out of the gateway code.

#### Nutrition Service

The nutrition service is the authority for:

- branded product lookup
- generic food lookup
- candidate generation for packaged and plated meals
- confidence scoring
- correction handling
- adaptive ranking
- meal logging
- audit history

The service exposes a small API that Hermes can call. Hermes should not read the imported nutrition tables directly.

#### Postgres

Postgres stores:

- canonical branded products imported from `shopping_bot`
- generic food entries for plated-meal fallback
- product aliases and OCR aliases
- meal logs
- meal items
- meal images
- candidate sets shown to the user
- correction events
- learned user defaults

The database should preserve both nutrition facts and interaction history. That separation matters. Nutrition facts are canonical data. Adaptive behavior comes from ranking and defaults, not from rewriting the source nutrition facts because the user corrected one meal.

#### Shopping-Bot Importer

The current `shopping_bot` local file should be treated as an import source, not a live runtime dependency. A one-way importer should load its food-label records into Postgres on demand or on a schedule.

That gives v1 immediate grounding from real label data while creating a clean migration path to a proper nutrition backend.

## Data Model

V1 needs a small but explicit model:

- `products`
  Stores canonical branded food records, serving definitions, calories, macros, and any available micros.
- `product_aliases`
  Stores normalized names, OCR variants, and brand/product text that should resolve to a canonical product.
- `generic_foods`
  Stores generic nutrition entries for foods that are commonly detected in plated meals.
- `meal_logs`
  Stores one meal event per user submission.
- `meal_items`
  Stores the resolved foods and portions for a logged meal.
- `meal_images`
  Stores references to the uploaded image cache paths or durable image identifiers.
- `candidate_sets`
  Stores the ranked options shown back to the user, with confidence and explanation text.
- `corrections`
  Stores what the bot proposed, what the user selected or typed, and how the final result differed.
- `user_defaults`
  Stores learned preferences such as recurring meals, preferred aliases, and typical portions.

This model is enough for v1 logging and learning without dragging in broader health-platform concerns.

## Request Flow

1. The user sends one or more meal photos to the nutrition bot in a direct message, optionally with a caption.
2. Hermes caches the images and forwards an analysis request to the nutrition service.
3. The nutrition service runs two grounded interpretation paths:
   - `packaged-food path`: OCR and visual product recognition for brand, product name, serving text, and label cues
   - `plated-meal path`: food-item and portion estimation for mixed meals
4. The nutrition service grounds those guesses against canonical data:
   - imported `shopping_bot` product records for branded items
   - generic food entries for plated-meal fallback
   - learned correction history and personal defaults for ranking
5. The service chooses one of two response modes:
   - `high-confidence packaged match`: auto-log the meal and return a compact confirmation with an obvious correction path
   - `uncertain or plated-meal match`: return `2-3` ranked candidates for the user to choose from
6. When candidate selection is needed, the service returns `2-3` ranked candidates with:
   - meal title
   - estimated calories, protein, carbs, and fat
   - optional micronutrients when the source supports them
   - confidence
   - short explanation of why each candidate ranked where it did
7. Hermes replies with inline buttons for the ranked choices when needed and supports free-text correction in the same conversation in both modes.
8. The user's button pick or free-text correction is sent back to the nutrition service.
9. The nutrition service resolves the final meal log, stores the correction event, updates learned defaults, and returns the logged result.
10. Hermes replies with a short text confirmation.

## Candidate And Correction UX

V1 should optimize for fast logging without pretending uncertainty does not exist.

### Default Reply

The first reply after analysis should be compact:

- meal or product name
- calories
- protein
- carbs
- fat
- short confidence or explanation line

Micronutrients should appear only when the source is good enough or when the user explicitly asks for detail.

### Candidate Selection

For v1, high-confidence auto-log is allowed only for strong branded packaged-food matches. Plated meals should not silently auto-log in v1, even when the ranking is good. They should still surface `2-3` candidates so the user can correct portions and meal composition quickly.

When the service is not confident enough to auto-log, Hermes should present `2-3` candidates using inline buttons. Each candidate should map to a stable candidate identifier from the nutrition service, not to fragile text parsing in Telegram.

### Free-Text Correction

Buttons cover the common path. Free-text corrections cover the edge cases. The free-text path should allow short corrections such as:

- `2 eggs and one slice of sourdough`
- `this was the Carman's chocolate protein bar`
- `same tuna salad as yesterday but double portion`

Hermes should pass that correction text to the nutrition service, which re-ranks or resolves the meal using the stored candidate context plus the correction text.

## Adaptive Learning Rules

The system should learn ranking behavior, not rewrite nutrition truth.

It should learn from:

- accepted candidates
- rejected candidates
- free-text corrections
- recurring meal names
- recurring brand choices
- typical portion choices
- useful aliases such as the user's shorthand for a known meal

It should not:

- silently edit canonical nutrition facts in `products`
- infer permanent facts from one ambiguous photo
- auto-log low-confidence meals without showing candidates

This is the core safety rule for the feature. The bot can learn what the user usually means. It must not learn new nutrition facts from vibes.

## Error Handling

Failures should degrade cleanly and visibly.

- If the image is unreadable, the bot should say so and ask for a clearer photo or a text description.
- If the nutrition service cannot ground a branded product well, it should return ranked candidates with explicit low-confidence wording.
- If the plated-meal estimate is weak, the bot should present its best candidates and invite correction rather than logging a guess as fact.
- If the service is unavailable, Hermes should return a short failure message and avoid partial logging.
- If the correction text is too ambiguous to resolve, the service should return a narrower follow-up prompt instead of pretending it understood.

## Testing

V1 needs all three test layers.

### Unit

- importer normalization from the current `shopping_bot` local-file shape into canonical nutrition records
- candidate ranking rules
- confidence thresholds
- correction parsing
- adaptive-learning updates
- response formatting

### Integration

- Hermes DM photo intake to nutrition-service analysis request
- inline-button candidate selection round trip
- free-text correction round trip
- Postgres persistence for meal logs, candidate sets, and corrections
- importer load into Postgres

### E2E

- real Telegram DM to the dedicated nutrition bot
- real image upload
- candidate response in text with buttons
- successful button choice
- successful free-text correction
- final meal log persistence and audit trail

## Operations

Run the system as two deployable units:

- `Hermes nutrition bot`
- `nutrition service`

The Hermes bot should use its own Telegram token and its own Hermes profile. It should have a narrow toolset. This bot should behave like a food clerk, not a general-purpose agent with a caffeine problem.

The nutrition service should own Postgres migrations, importer runs, and audit queries. Hermes should call it over HTTP. That boundary is simpler to secure, test, and evolve than direct database access from the gateway.

## Rollout

V1 rollout should be staged:

1. Build the nutrition service with Postgres and importer support for the current `shopping_bot` file.
2. Stand up the dedicated Telegram nutrition bot profile in Hermes.
3. Wire the DM photo analysis and candidate-selection loop.
4. Add correction handling and adaptive ranking.
5. Run end-to-end tests with real Telegram messages and representative meal photos.
6. Seed the database from the current `shopping_bot` data before normal use.

This rollout keeps the riskiest parts separate: data migration, image interpretation, and Telegram UX.
