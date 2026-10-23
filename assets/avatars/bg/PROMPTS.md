# 사내톡 프로필 배경 — 생성 작업 지시서 (Codex·GPT 용)

10/23 겸이 "배경사진 각 누나들의 일상적인 사진으로, 얼굴 나오게". 원본 데이터는 `assets/avatars/profiles.json` 의 `bg_prompt` (이 파일은 그걸 작업 순서로 펼친 것 — 프롬프트를 고치려면 profiles.json 을 고치고 이 표를 다시 만들 것).

## 작업 규칙

1. 누나마다: **참조 이미지** `assets/avatars/<키>.png`(프사)를 넣고 아래 프롬프트로 생성 → 같은 인물·얼굴 유지.
2. 결과는 **세로 9:16**, JPG, 긴 변 1600px 안팎·500KB 안팎 → `assets/avatars/bg/<키>.jpg` 로 저장(이 폴더). 파일명 = 키 그대로.
3. 금지: 글자·로고·브랜드, 노출·선정적 연출, 실존 인물 닮게 하기, 다른 사람 얼굴.
4. 터미널(사내톡 › 👥 프로필)은 이 경로를 바로 읽음 — 없으면 그라디언트. 커밋만 하면 반영(5분 캐시).

## 목록 (26명)

### pb

- 참조: `assets/avatars/pb.png` → 저장: `assets/avatars/bg/pb.jpg`

> Same woman as the attached profile photo (Korean, 29), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Warm small cafe table by a rainy window in a Seoul alley at dusk, latte and a fish-shaped pastry bag, open notebook with pen, soft string lights. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### cio

- 참조: `assets/avatars/cio.png` → 저장: `assets/avatars/bg/cio.jpg`

> Same woman as the attached profile photo (Korean, 36), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Quiet Saturday morning desk in a Seoul apartment, fountain pen and ink bottle beside an open hardbound book, neat stack of binders, soft window light. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### alloc

- 참조: `assets/avatars/alloc.png` → 저장: `assets/avatars/bg/alloc.jpg`

> Same woman as the attached profile photo (Korean, 36), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Corner seat of a quiet neighborhood cafe in Seoul, the same ceramic latte cup on a wooden table, small potted plant, phone face-down, calm afternoon light. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### macro

- 참조: `assets/avatars/macro.png` → 저장: `assets/avatars/bg/macro.jpg`

> Same woman as the attached profile photo (Korean, 34), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Sunday kitchen table covered with newspaper clippings, scissors, washi tape and a hand-written monthly calendar, coffee mug, morning sun. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### bonds

- 참조: `assets/avatars/bonds.png` → 저장: `assets/avatars/bg/bonds.jpg`

> Same woman as the attached profile photo (Korean, 35), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Cozy sofa corner at night with a half-finished grey knitted scarf, yarn balls and needles, warm floor lamp, cup of barley tea, Korean apartment living room. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### realestate

- 참조: `assets/avatars/realestate.png` → 저장: `assets/avatars/bg/realestate.jpg`

> Same woman as the attached profile photo (Korean, 33), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Narrow old Seoul alley with hanok rooftops and brick walls in late afternoon light, camera strap around her wrist. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### quant

- 참조: `assets/avatars/quant.png` → 저장: `assets/avatars/bg/quant.jpg`

> Same woman as the attached profile photo (Korean, 31), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Board game night table from above, dice, wooden tokens and cards, a notebook with tally marks and a small histogram sketch, warm pendant light. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### analyst

- 참조: `assets/avatars/analyst.png` → 저장: `assets/avatars/bg/analyst.jpg`

> Same woman as the attached profile photo (Korean, 30), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Weekend desk with an open PC case, unbranded motherboard, memory sticks and screwdriver, installing a part, soft daylight, small Seoul studio apartment. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### derivs

- 참조: `assets/avatars/derivs.png` → 저장: `assets/avatars/bg/derivs.jpg`

> Same woman as the attached profile photo (Korean, 32), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Half-finished 1000-piece jigsaw puzzle on a wooden table, pieces sorted into labeled trays, desk lamp at night, cup of tea. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### data

- 참조: `assets/avatars/data.png` → 저장: `assets/avatars/bg/data.jpg`

> Same woman as the attached profile photo (Korean, 29), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Neatly organized pantry shelf with identical glass jars, each with a blank white label, a label maker on the counter, clean morning light, Korean apartment kitchen. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### frm

- 참조: `assets/avatars/frm.png` → 저장: `assets/avatars/bg/frm.jpg`

> Same woman as the attached profile photo (Korean, 35), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Small boxing gym at night, worn red heavy bag hanging, wrapped gloves resting on a bench, dim warm lights, Seoul neighborhood. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### behavior

- 참조: `assets/avatars/behavior.png` → 저장: `assets/avatars/bg/behavior.jpg`

> Same woman as the attached profile photo (Korean, 34), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Binoculars and a small field notebook on a wooden bench beside Han River reeds at dawn, egrets in soft mist, quiet and still. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### pm

- 참조: `assets/avatars/pm.png` → 저장: `assets/avatars/bg/pm.jpg`

> Same woman as the attached profile photo (Korean, 33), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Minimalist campsite in a Korean pine forest at evening, one folding chair, small lantern, enamel mug, short checklist clipped to a table. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### ops

- 참조: `assets/avatars/ops.png` → 저장: `assets/avatars/bg/ops.jpg`

> Same woman as the attached profile photo (Korean, 35), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Granite mountain trail near Seoul at sunrise, wearing a small backpack, checklist card tucked in a side pocket, city skyline in morning haze. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### dev

- 참조: `assets/avatars/dev.png` → 저장: `assets/avatars/bg/dev.jpg`

> Same woman as the attached profile photo (Korean, 29), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Late-night desk with a custom mechanical keyboard and keycap puller, scattered switches, dual monitors glowing with code, instant noodle cup. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### scribe

- 참조: `assets/avatars/scribe.png` → 저장: `assets/avatars/bg/scribe.jpg`

> Same woman as the attached profile photo (Korean, 28), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Film camera on a sunny cafe windowsill in the morning, small notebook with times jotted, film canisters, iced coffee, Seoul street softly blurred outside. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### edu

- 참조: `assets/avatars/edu.png` → 저장: `assets/avatars/bg/edu.jpg`

> Same woman as the attached profile photo (Korean, 31), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Pottery one-day class workshop, rows of unglazed cups on shelves, warm afternoon light, Seoul studio. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### eval

- 참조: `assets/avatars/eval.png` → 저장: `assets/avatars/bg/eval.jpg`

> Same woman as the attached profile photo (Korean, 28), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Dimly lit puzzle room with an old wooden chest, brass padlock and a ring of keys on a table, moody warm spotlight. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### household

- 참조: `assets/avatars/household.png` → 저장: `assets/avatars/bg/household.jpg`

> Same woman as the attached profile photo (Korean, 36), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Korean home kitchen counter on Sunday morning, homemade side dishes in glass containers, cutting board, packing lids, sunlight through window. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### life

- 참조: `assets/avatars/life.png` → 저장: `assets/avatars/bg/life.jpg`

> Same woman as the attached profile photo (Korean, 32), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Han River running path in Seoul at dawn, track curving along the water, bridge in pink morning light. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### verify

- 참조: `assets/avatars/verify.png` → 저장: `assets/avatars/bg/verify.jpg`

> Same woman as the attached profile photo (Korean, 30), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Two identical loaves of bread cooling side by side on a rack, digital kitchen scale and a written recipe card, flour-dusted counter, soft kitchen light. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### peer

- 참조: `assets/avatars/peer.png` → 저장: `assets/avatars/bg/peer.jpg`

> Same woman as the attached profile photo (Korean, 33), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Seats of a small independent cinema in Seoul, screen glowing before the film, a single ticket stub and notebook on an armrest. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### audit

- 참조: `assets/avatars/audit.png` → 저장: `assets/avatars/bg/audit.jpg`

> Same woman as the attached profile photo (Korean, 36), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Narrow used bookstore aisle in Seoul with towering stacks of old books, dusty afternoon light. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### hf

- 참조: `assets/avatars/hf.png` → 저장: `assets/avatars/bg/hf.jpg`

> Same woman as the attached profile photo (Korean, 34), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Indoor bouldering gym after work, chalk dust in the air, dramatic lighting. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### uxui

- 참조: `assets/avatars/uxui.png` → 저장: `assets/avatars/bg/uxui.jpg`

> Same woman as the attached profile photo (Korean, 30), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Minimal white art gallery in Seoul, bench facing large abstract paintings, small blank wall captions, soft diffused skylight. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.

### maint

- 참조: `assets/avatars/maint.png` → 저장: `assets/avatars/bg/maint.jpg`

> Same woman as the attached profile photo (Korean, 31), keep her face identical. Candid everyday photo of her, face clearly visible, natural relaxed expression, casual outfit. Scene: Small apartment balcony garden in Seoul, rows of potted herbs and succulents, watering can, a phone timer beside a bicycle tool kit, gentle morning light. Photorealistic smartphone photo, natural light, vertical 9:16, no text, no logos.
