# 프론트 프로필 이미지 — 2026-10-24

- 대상: 신설 프론트 담당자 `front` (운영본부, 30세).
- 생성 도구: 내장 imagegen. 기존 `AVATAR_PROMPTS.md`의 front 행과 `profiles.json`의 front.bg_prompt를 기준으로 생성.
- 프사: `assets/avatars/front.png`. 배경: `assets/avatars/bg/front.jpg`.
- 배경은 생성한 프사를 얼굴 참조로 사용했다. 기존 승인된 다른 담당자 이미지는 유지한다.
- 영향: 사내톡 프로필·조직도·프로필 배경. 기존 파일명 규칙으로 자동 연결되므로 화면 코드 변경 없음.
- 롤백: 이 커밋을 revert하면 기존 이니셜·그라디언트 대체 화면으로 돌아간다.
- 검증: 사내톡 피드 테스트 3개 통과. Chrome 헤드리스 390px·1300px에서 프사 512px 로딩·배경 JPEG 로딩·가로 넘침 없음·페이지 오류 없음 확인. 모바일 화면 캡처 육안 확인. board·check_functions·check_rules_terms 통과.

## 프로필 생성 프롬프트

Use case: photorealistic-natural. Asset type: market-screener messenger profile portrait for fictional front-end developer desk 'front', age 30. Photorealistic Korean ID/profile photo (jeungmyeong-sajin framing), front-facing head and shoulders, centered, plain deep teal studio background, soft even studio lighting, natural skin texture, refined confident adult Korean woman with playful creator energy. Distinctive rounded lively face, rounded nose tip, full lips, sparkling large eyes, subtle pearl eye shadow and coral-brick lipstick, no glasses. Long S-curl dark cherry-brown hair falling below shoulders, thin silver ear cuff on one ear. Cobalt blue satin shirt blouse over white inner top, fully clothed. Straight-on gaze, mischievous half smile with one eye very slightly narrowed. Keep top of hair and shoulders fully in frame, face readable at small circular avatar scale. Square 1:1 portrait, realistic camera photograph, not illustration. Original fictional person, no resemblance to a specific real person, no text, no logos, no watermark.

## 배경 생성 프롬프트

Use case: identity-preserve. Asset type: vertical messenger profile background photo for fictional Korean front-end developer 'front', age 30. Reference image 1: identity reference, use exactly this same adult woman's face, rounded nose, eyes, full lips, long dark cherry-brown S-curl hair and thin silver ear cuff. Create a NEW everyday smartphone selfie of her, not a studio portrait. Outfit: cobalt blue satin shirt blouse over white inner top, fully clothed and tasteful. Scene: small nail-art studio table in Hapjeong in the evening. She is taking a realistic selfie herself with one arm extended toward the camera; her other hand is held beside her face showing freshly painted glossy gradient nails. Natural anatomically correct hands. Playful half smile with one eye slightly narrowed, direct eye contact with camera. A laptop beside her displays colorful abstract interface blocks with NO readable text; scattered color swatch chips and nail-polish bottles. Real casual clutter and warm evening studio lighting. Smartphone front-camera wide perspective, realistic slightly warm HDR, natural skin pores and flyaway hairs, subtle shadow noise, everyday unedited snapshot, no beauty filter, no airbrushing, no portrait-mode artificial blur. Vertical 9:16 composition, face in upper half and desk context below, usable as messenger wallpaper. Preserve her reference identity and styling precisely. No text, no logos, no watermark, no UI overlays.

