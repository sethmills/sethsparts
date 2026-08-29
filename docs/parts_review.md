# Parts to review

Two lists: **71 parts I identified with only medium/low confidence** (confirm or correct), and further below, **242 parts too ambiguous to research at all** (need your read on what they actually are), organized by drawer/container. Generic hardware (screws, wire, connectors, etc.) is excluded from both — those never needed enrichment.

## Section 1 — Confirm or correct (medium/low confidence matches)

- [ ] **1.3" 128x64 oled** (id 341) — guessed: *Generic 1.3" 128x64 monochrome OLED display module (SH1106 driver; commodity item, sold under many brands)* (medium)
      Why uncertain: Generic commodity item sold under many brand names on Amazon/eBay/AliExpress with no single canonical manufacturer; linked to a well-documented vendor reference page rather than one storefront listing.
      https://sethsparts.com/parts/341/

- [ ] **1.8 inch spi tft module** (id 583) — guessed: *Generic 1.8" SPI color TFT display module (ST7735 driver, 128x160), commonly a clone of the Adafruit 1.8" TFT breakout* (medium)
      Why uncertain: Sold under many brand names as near-identical clones; Adafruit's version (PID 618) is the most thoroughly documented reference and is used here as the representative link, though the exact board on hand may be an unbranded clone.
      https://sethsparts.com/parts/583/

- [ ] **12v relay module** (id 495) — guessed: *Generic single-channel 12V relay module (commodity item, sold under many brands e.g. SainSmart/Keyestudio)* (medium)
      Why uncertain: Generic commodity relay module with no single canonical manufacturer; nearly identical boards are sold under many brand names (Keyestudio, SainSmart, generic AliExpress/eBay listings).
      https://sethsparts.com/parts/495/

- [ ] **2ch relay board** (id 57) — guessed: *Generic 2-channel 5V relay module (commodity item, e.g. SainSmart 2-Channel Relay Module)* (medium)
      Why uncertain: Generic commodity item sold under many brand names (SainSmart, Keyestudio, SunFounder, etc.) with no single canonical manufacturer; the SainSmart listing (now discontinued) is used as a representative reference.
      https://sethsparts.com/parts/57/

- [ ] **8 ch relay board** (id 370) — guessed: *Generic 8-channel 5V relay module (commodity item, e.g. SainSmart/JBtek 8-Channel Relay Module)* (medium)
      Why uncertain: Generic commodity item widely sold under many brand names (SainSmart, JBtek, generic AliExpress/eBay listings) with no single canonical manufacturer.
      https://sethsparts.com/parts/370/

- [ ] **FTDI breakout board** (id 365) — guessed: *Generic FT232RL USB-to-serial breakout board (commodity item, e.g. SparkFun-style FTDI Basic breakout)* (medium)
      Why uncertain: Sold under many brand names (SparkFun, Adafruit "FTDI Friend", generic clones) with no single canonical manufacturer; SparkFun's well-documented version is used here as the representative reference.
      https://sethsparts.com/parts/365/

- [ ] **adafruit bluefruit board** (id 363) — guessed: *Bluefruit LE Friend - Bluetooth Low Energy 4.0 - nRF51822 [v3.0]* (medium)
      Why uncertain: The label is generic - Adafruit has sold many distinct 'Bluefruit' products over the years (UART Friend v2 #2479, this SPI/UART Friend v3.0 #2267, SPI Friend #2633, Feather 32u4 Bluefruit LE, Feather nRF52832, Bluefruit LE Sniffer, EZ-Link, etc). Matched to the standalone 'Bluefruit LE Friend' breakout since the inventory calls it a 'board' rather than a 'feather' or 'shield'. The learn guide has no separate Pinouts sub-page (fetch returned 404), and Adafruit's own downloads page links only to Nordic's nRF51822 product page, not a direct PDF, so datasheet_url is left null.
      https://sethsparts.com/parts/363/

- [ ] **adafruit cc3000 wifi board** (id 362) — guessed: *Adafruit HUZZAH CC3000 WiFi Breakout with Onboard Antenna [v1.1]* (medium)
      Why uncertain: Adafruit sold this as both a breakout (with onboard ceramic antenna, product 1469, or with a uFL connector for external antenna, product 1510) and as an Arduino shield - the generic label doesn't distinguish. Picked the onboard-antenna breakout as the most common variant. Product is discontinued/out of stock; the learn guide is an older single/multi-page format with no distinct Pinouts sub-page, and no direct chip datasheet PDF is linked from Adafruit's own pages (they link out to TI's product page instead).
      https://sethsparts.com/parts/362/

- [ ] **adafruit feather board** (id 24) — guessed: *Adafruit Feather (generic/unspecified variant)* (low)
      Why uncertain: Deliberately not matched to a specific SKU per instructions - Adafruit sells dozens of distinct 'Feather' boards and the inventory label gives no way to tell which chip/variant this is. Linked to the Feather family overview/introduction guide instead of guessing a specific product.
      https://sethsparts.com/parts/24/

- [ ] **adafruit feather s3 board** (id 42) — guessed: *Adafruit ESP32-S3 Feather with 4MB Flash 2MB PSRAM (STEMMA QT/Qwiic)* (medium)
      Why uncertain: Label 'feather s3 board' is generic among several ESP32-S3 Feather SKUs Adafruit sells (plain #5477/#5323, ESP32-S3 TFT Feather #5483, ESP32-S3 Reverse TFT Feather #5691, w.FL antenna version #5885, plus the third-party 'FeatherS3' by Unexpected Maker #5399). Picked the plain STEMMA QT ESP32-S3 Feather (4MB/2MB PSRAM) as the most 'default' interpretation, but this is a guess.
      https://sethsparts.com/parts/42/

- [ ] **adafruit macropad** (id 983) — guessed: *Adafruit MacroPad RP2040* (medium)
      Why uncertain: Adafruit sells this as a bare-bones PCB-only version (#5100), a Starter Kit with switches/keycaps/enclosure (#5128, part of ADABOX019), and a separate enclosure/hardware add-on pack (#5103). Linked to the Starter Kit as the most complete/common variant; the physical inventory item could be any of these.
      https://sethsparts.com/parts/983/

- [ ] **adafruit metro board** (id 321) — guessed: *Adafruit METRO 328 Fully Assembled - Arduino IDE compatible [ATmega328]* (medium)
      Why uncertain: Distinct from Metro Mini (id 471) per instructions. 'Metro' could also refer to the Metro M0 Express or Metro M4 Express (different, faster SAMD chips) - picked the original ATmega328-based Metro as the default/classic 'Metro'. There isn't a dedicated Learn System guide page for this exact board (only project guides like 'Experimenter's Guide for Metro' and the general 'How to Choose a Microcontroller' reference it), so learn_guide_url and pinout_image_url are left null; no direct chip datasheet PDF is linked from Adafruit's own pages either (they link to Microchip/Atmel's product page).
      https://sethsparts.com/parts/321/

- [ ] **adafruit metro mini** (id 471) — guessed: *Adafruit Metro Mini 328 V2 - Arduino-Compatible - 5V 16MHz [STEMMA QT / Qwiic]* (medium)
      Why uncertain: The original (V1, CP2104-based, no STEMMA QT) Metro Mini has been superseded by this V2; if the physical part predates ~2022 it may actually be the older V1 board, which looks nearly identical but lacks the STEMMA QT connector. No direct chip datasheet PDF is linked from Adafruit's own pages.
      https://sethsparts.com/parts/471/

- [ ] **adafruit minipitft** (id 307) — guessed: *Adafruit Mini PiTFT 1.3" - 240x240 TFT Add-on for Raspberry Pi* (medium)
      Why uncertain: Per hint, matched to the Mini PiTFT family. Adafruit's Mini PiTFT guide covers two closely related products sharing the same connector/pinout: the 1.3" 240x240 (#4484, matched here) and the 1.14" 240x135 (#4302) - the generic 'minipitft' label can't distinguish which one is actually in the drawer.
      https://sethsparts.com/parts/307/

- [ ] **adfruit feather board** (id 31) — guessed: *Adafruit Feather (general board family/form-factor - specific chip variant unspecified)* (low)
      Why uncertain: Per the hint, "adfruit" is a typo of "adafruit." Too generic to guess a specific chip variant with confidence, so linked to Adafruit's own Feather family overview instead of a specific product SKU.
      https://sethsparts.com/parts/31/

- [ ] **amiga keyboard** (id 1000) — guessed: *Commodore Amiga keyboard (generic - specific model, e.g. A500/A1200/A2000/A3000/A4000, not specified)* (low)
      Why uncertain: "Amiga keyboard" doesn't specify which Amiga model it came from (each uses a different keyboard/membrane design), so no single specific product page applies; image_url is a Wikimedia Commons page showing an A500 system including its keyboard, not a bare direct image file link.
      https://sethsparts.com/parts/1000/

- [ ] **arduino** (id 293) — guessed: *Unspecified Arduino board (too vague to identify a specific product)* (low)
      Why uncertain: No identifying details given; too vague to match a specific product. Linked to Arduino's own homepage rather than guessing a specific board.
      https://sethsparts.com/parts/293/

- [ ] **arduino assorted parts and add on boards** (id 1069) — guessed: *No single product - mixed/assorted Arduino parts and add-on boards* (low)
      Why uncertain: Per the hint, this is a vague catch-all description covering multiple unspecified items, not a single identifiable product - deliberately left unmatched rather than fabricating a specific board.
      https://sethsparts.com/parts/1069/

- [ ] **arduino board** (id 555) — guessed: *Unspecified Arduino board (too vague to identify a specific product)* (low)
      Why uncertain: Same ambiguity as item 293 ("arduino"); no identifying details given, so left generic rather than guessing a specific board.
      https://sethsparts.com/parts/555/

- [ ] **arduino boards** (id 553) — guessed: *Unspecified Arduino boards (plural, too vague to identify specific products)* (low)
      Why uncertain: Plural version of items 293/555; still no identifying details given, so left generic rather than guessing specific boards.
      https://sethsparts.com/parts/553/

- [ ] **arduino clone boards** (id 368) — guessed: *Generic unbranded Arduino-compatible "clone" board(s) (e.g. ATmega328P-based Uno clone), commodity item with no canonical manufacturer* (low)
      Why uncertain: By definition these are unbranded/non-canonical products (that is what makes them "clones"); no single manufacturer, specific model, or product page applies.
      https://sethsparts.com/parts/368/

- [ ] **arduino dc+stepper motor hat** (id 328) — guessed: *Adafruit DC & Stepper Motor HAT for Raspberry Pi (PID 2348), or possibly Adafruit's equivalent Motor Shield for Arduino* (medium)
      Why uncertain: Item is labeled "arduino" but "HAT" is Raspberry-Pi-specific terminology - likely a labeling mix-up by the cataloger, or they may have meant Adafruit's similarly-named Motor/Stepper Shield for Arduino (adafruit.com/product/1438). Flagging this ambiguity rather than picking one silently.
      https://sethsparts.com/parts/328/

- [ ] **arduino wifi module** (id 504) — guessed: *Generic ESP8266-based WiFi module/shield for Arduino (commodity item, distinct from the official discontinued Arduino WiFi Shield)* (low)
      Why uncertain: Ambiguous: could be Arduino's own official (now-retired) WiFi Shield (arduino.cc/en/Main/ArduinoWiFiShield, based on the HDG204 module), or - more likely given hobbyist prevalence - a generic ESP8266/ESP-01 WiFi module/shield. Left low confidence given this ambiguity; distinct from item 405 (ESP32 dev board) and 479 (ESP-12E dev board), which are standalone boards rather than "modules."
      https://sethsparts.com/parts/504/

- [ ] **attiny85 board** (id 403) — guessed: *Digispark ATtiny85 USB development board* (medium)
      Why uncertain: The original creator (Digistump) is defunct; boards sold today are third-party clones/continuations of the open-source Digispark design, so no single current canonical manufacturer exists. "ATtiny85 board" could in principle refer to a different, non-Digispark ATtiny85 breakout, but Digispark is by far the most common.
      https://sethsparts.com/parts/403/

- [ ] **bleduinio shield** (id 258) — guessed: *Likely "BLEduino" (Kytelabs) - a 2013 crowdfunded Arduino-Leonardo-compatible board with onboard Bluetooth Low Energy (mangled/typo'd as "bleduinio")* (low)
      Why uncertain: Name is a probable mangled typo of "BLEduino" per the hint. Could alternatively be a generic BLE/Bluetooth shield (e.g. Adafruit Bluefruit LE Shield, RedBearLab BLE Shield). Low confidence because BLEduino was a small 2013 Kickstarter product that is long discontinued with limited surviving official documentation, so the exact match can't be fully confirmed from the label alone.
      https://sethsparts.com/parts/258/

- [ ] **bluetooth shield** (id 259) — guessed: *Generic classic-Bluetooth (HC-05/HC-06 style) shield or module for Arduino (commodity item, no canonical manufacturer)* (low)
      Why uncertain: Too generic to identify a specific brand/product - could be any of many near-identical HC-05/HC-06 shields, or a BLE shield such as Adafruit's Bluefruit LE. Treated as a separate, unrelated entry from item 258 ("bleduinio shield").
      https://sethsparts.com/parts/259/

- [ ] **c64 internal shielding** (id 1006) — guessed: *Generic Commodore 64 internal RF shield (metal shielding can/plate) - a salvage/replacement part, not a manufactured "product"* (low)
      Why uncertain: Per the hint, this is a literal internal metal shielding part, not a purchasable electronic "product" with a canonical manufacturer or model number - described generically with a reference article in place of a storefront link.
      https://sethsparts.com/parts/1006/

- [ ] **esp 12e dev board** (id 479) — guessed: *NodeMCU (ESP-12E module) development board (commodity item, sold under many brands)* (medium)
      Why uncertain: Generic/commodity dev board manufactured and sold by many vendors under the community "NodeMCU" open-source design, with no single canonical manufacturer; components101 used as a well-documented reference rather than one storefront listing.
      https://sethsparts.com/parts/479/

- [ ] **esp 32 dev board** (id 405) — guessed: *Generic ESP32 development board (commodity item, e.g. "DOIT ESP32 DevKit V1" style 30-pin/38-pin clone)* (medium)
      Why uncertain: Commodity item sold under many brand names/unbranded clones with no single canonical manufacturer; linked to a well-documented reference/pinout page instead of a single storefront listing.
      https://sethsparts.com/parts/405/

- [ ] **flora rgb neopixel v2** (id 444) — guessed: *Flora RGB Smart NeoPixel - Pack of 4 (Adafruit product #1260)* (medium)
      Why uncertain: Product ID #1260 is the same physical listing across revisions; hand-written label says 'v2' but current page describes v3 (SK6812 chip) -- datasheet omitted rather than risk citing the wrong chip.
      https://sethsparts.com/parts/444/

- [ ] **fluke multimeter** (id 941) — guessed: *Fluke digital multimeter (brand identified, no model number given)* (medium)
      Why uncertain: Brand unambiguous, exact model unknown. Linked to Fluke's multimeter category page.
      https://sethsparts.com/parts/941/

- [ ] **gps module** (id 517) — guessed: *Generic GPS receiver module (commodity item, no specific product indicated)* (low)
      Why uncertain: No specific module indicated by name.
      https://sethsparts.com/parts/517/

- [ ] **hdmi breakout board** (id 128) — guessed: *generic HDMI breakout board (commodity prototyping item)* (low)
      Why uncertain: Used Adafruit's HDMI Plug Breakout Board (3119) as representative example only.
      https://sethsparts.com/parts/128/

- [ ] **large motor drivers** (id 949) — guessed: *Generic high-current H-bridge motor driver module (commodity item, e.g. BTS7960-based board)* (low)
      Why uncertain: No brand/model given; BTS7960-based modules used as representative reference.
      https://sethsparts.com/parts/949/

- [ ] **led ring neopixel** (id 64) — guessed: *generic Adafruit NeoPixel Ring (commodity item -- sold in 12, 16, 24, and 60-LED/quarter sizes)* (low)
      Why uncertain: Hand-written label gives no LED count or RGB/RGBW variant, so no single specific product can be confidently matched.
      https://sethsparts.com/parts/64/

- [ ] **logic analyzer** (id 857) — guessed: *Generic 24MHz 8-channel USB logic analyzer (Cypress FX2/FX2LP-based clone, sigrok/PulseView-compatible)* (medium)
      Why uncertain: Could be a genuine Saleae unit, but generic FX2 clone is far more common in hobbyist workshops.
      https://sethsparts.com/parts/857/

- [ ] **neopixel quarter ring** (id 448) — guessed: *Adafruit NeoPixel 1/4 60 Ring - 5050 RGB LED w/ Integrated Drivers* (medium)
      Why uncertain: Verified as a real, specific Adafruit product (#1768), 1/4 of the 60-LED ring (15 LEDs per piece).
      https://sethsparts.com/parts/448/

- [ ] **neopixel ring** (id 443) — guessed: *generic Adafruit NeoPixel Ring (commodity item -- sold in 12, 16, 24, and 60-LED/quarter sizes)* (low)
      Why uncertain: Same ambiguity as item 64 -- no LED count specified, treated as a generic/family match.
      https://sethsparts.com/parts/443/

- [ ] **pcb breakout board** (id 159) — guessed: *Generic PCB breakout board (unspecified chip/purpose - commodity component category)* (low)
      Why uncertain: Essentially unidentifiable beyond general category.
      https://sethsparts.com/parts/159/

- [ ] **pi zero** (id 39) — guessed: *Raspberry Pi Zero (original, no wireless)* (medium)
      Why uncertain: Could be Zero, Zero W, or Zero 2 W; picked original as base/iconic match.
      https://sethsparts.com/parts/39/

- [ ] **pi zero cases** (id 43) — guessed: *generic Raspberry Pi Zero case(s) (commodity accessory)* (low)
      Why uncertain: Plural, no brand specified; could be third-party equivalents.
      https://sethsparts.com/parts/43/

- [ ] **pi zero with expansion board** (id 37) — guessed: *generic Raspberry Pi Zero plus an unspecified GPIO expansion board/HAT (no single product)* (low)
      Why uncertain: No specific expansion board named; hundreds of official/third-party HATs exist.
      https://sethsparts.com/parts/37/

- [ ] **raspberry pi boards** (id 634) — guessed: *generic assortment of Raspberry Pi single-board computers (unspecified models)* (low)
      Why uncertain: Extremely generic plural label with no model info.
      https://sethsparts.com/parts/634/

- [ ] **raspi breakout boards** (id 461) — guessed: *Generic Raspberry Pi GPIO breakout board(s) (commodity item, e.g. Pi T-Cobbler style)* (low)
      Why uncertain: No specific product named; Adafruit Pi T-Cobbler Plus linked as representative example. Plural 'boards' may mean multiple items.
      https://sethsparts.com/parts/461/

- [ ] **raspi camera** (id 55) — guessed: *Raspberry Pi Camera Module 2 (8MP, Sony IMX219 sensor)* (medium)
      Why uncertain: Label only says 'raspi camera' with no version given; Camera Module 2 (IMX219) picked as the representative match.
      https://sethsparts.com/parts/55/

- [ ] **raspi camera cables** (id 454) — guessed: *generic Raspberry Pi CSI camera ribbon/flex cable (commodity item)* (medium)
      Why uncertain: No single specific cable identifiable; used official RPi Foundation 'Camera Cable' product as representative.
      https://sethsparts.com/parts/454/

- [ ] **raspi camera case** (id 18) — guessed: *generic Raspberry Pi camera module case/enclosure (commodity item)* (low)
      Why uncertain: No official RPi camera case exists; Adafruit product 3253 used as representative example only.
      https://sethsparts.com/parts/18/

- [ ] **raspi camera lense** (id 598) — guessed: *generic M12 (S-mount) replacement lens for Raspberry Pi camera board (commodity item, no canonical product)* (low)
      Why uncertain: Label likely a typo for 'lens'. No canonical single product — generic commodity category.
      https://sethsparts.com/parts/598/

- [ ] **raspi case** (id 155) — guessed: *generic Raspberry Pi case (commodity accessory, unspecified Pi model/brand)* (low)
      Why uncertain: No model/brand specified; possibly a near-duplicate of item 154.
      https://sethsparts.com/parts/155/

- [ ] **raspi gertboard** (id 635) — guessed: *Raspberry Pi Gertboard (GPIO expansion/prototyping board) — discontinued/legacy product* (medium)
      Why uncertain: Real historic product from ~2012, long out of production; no live official product page found, linked RPi Forums thread instead.
      https://sethsparts.com/parts/635/

- [ ] **raspi in case** (id 154) — guessed: *generic Raspberry Pi board housed in an unspecified case (commodity combo)* (low)
      Why uncertain: Likely describes physical state rather than a distinct product; possibly duplicate of item 155.
      https://sethsparts.com/parts/154/

- [ ] **raspi pan tilt mechanism** (id 636) — guessed: *Adafruit Mini Pan-Tilt Kit - Assembled with Micro Servos* (medium)
      Why uncertain: Similar kits also sold by Waveshare and others; exact kit owned not confirmable.
      https://sethsparts.com/parts/636/

- [ ] **raspi pinout guide** (id 149) — guessed: *GPIO pinout reference card (physical reference item, not an electronic product)* (low)
      Why uncertain: Not a product with a canonical manufacturer page; pinout.xyz linked as the closest real equivalent.
      https://sethsparts.com/parts/149/

- [ ] **raspi power supply** (id 165) — guessed: *Raspberry Pi official USB-C power supply (15W, 5.1V/3A) or similar official Pi power adapter* (medium)
      Why uncertain: Raspberry Pi sells several official supplies of different wattage (15W for Pi 4/400, 27W for Pi 5, older 12.5W micro-USB for earlier boards); which exact one was on hand is not specified, so this is a best-guess representative match rather than a confirmed SKU.
      https://sethsparts.com/parts/165/

- [ ] **raspi zero** (id 294) — guessed: *Raspberry Pi Zero W (Pi Zero family)* (medium)
      Why uncertain: Label just says 'raspi zero' with no W/2W qualifier; could be the plain Pi Zero, Zero W, or newer Zero 2 W. Picked Zero W as the most commonly encountered variant in hobbyist stock.
      https://sethsparts.com/parts/294/

- [ ] **relay board 8ch** (id 40) — guessed: *Generic 8-channel 5V relay module (commodity item, sold under many brands: SainSmart, SunFounder, JBtek, Kuongshun, etc.)* (medium)
      Why uncertain: This is a well-defined commodity product category (8-channel opto-isolated relay board) sold nearly identically under dozens of brand names; no single canonical manufacturer.
      https://sethsparts.com/parts/40/

- [ ] **relay module** (id 329) — guessed: *Generic relay module (commodity item, channel count/brand unspecified)* (low)
      Why uncertain: Label gives no channel count or brand, and overlaps with separately-listed items 40 (8ch), 324 (single), and 352 (small) relay boards in this same inventory, so it's ambiguous which physical board this entry refers to.
      https://sethsparts.com/parts/329/

- [ ] **rfid reader breakout board** (id 390) — guessed: *Adafruit PN532 NFC/RFID Controller Breakout Board (v1.6)* (medium)
      Why uncertain: Picked as the most well-documented specific 'RFID reader breakout board,' but other common breakouts (e.g. MFRC522-based modules) are equally plausible matches for a generic label like this, so exact identity is not certain.
      https://sethsparts.com/parts/390/

- [ ] **robot motor driver** (id 956) — guessed: *Generic H-bridge DC motor driver module (commodity item, commonly L298N or TB6612FNG based, sold under many brands)* (low)
      Why uncertain: 'Robot motor driver' is too generic to pin down a single product; picked TB6612FNG as a widely used representative example, but L298N-based boards and others are equally common in hobby robotics.
      https://sethsparts.com/parts/956/

- [ ] **servo controller board** (id 276) — guessed: *Adafruit 16-Channel 12-bit PWM/Servo Driver breakout (PCA9685)* (medium)
      Why uncertain: Adafruit's version is the best-documented match for a generic 'servo controller board,' but unbranded PCA9685 clone boards (very common on Amazon/eBay) are visually near-identical and equally plausible.
      https://sethsparts.com/parts/276/

- [ ] **single relay board** (id 324) — guessed: *Generic single-channel 5V relay module (commodity item, sold under many brands)* (medium)
      Why uncertain: Well-defined commodity category (single-channel 5V relay board); no single canonical manufacturer, virtually identical boards are sold under many brand names.
      https://sethsparts.com/parts/324/

- [ ] **small motor drivers** (id 945) — guessed: *Generic small motor driver module(s) (commodity, unspecified type/brand)* (low)
      Why uncertain: Label is a vague plural ('small motor drivers') with no distinguishing detail, so no single product can be responsibly matched.
      https://sethsparts.com/parts/945/

- [ ] **small neopixel ring** (id 445) — guessed: *Adafruit NeoPixel Ring - 16 x 5050 RGB LED* (medium)
      Why uncertain: Adafruit also sells a smaller 12-LED ring (1.5in diameter, product #1643); 'small' is relative, so it could be either the 12- or 16-LED variant.
      https://sethsparts.com/parts/445/

- [ ] **small relay module** (id 352) — guessed: *Generic small single-channel 5V relay module (commodity item, sold under many brands)* (low)
      Why uncertain: Overlaps heavily with items 324 (single relay board) and 329 (relay module) in this inventory; likely the same generic type of part recorded under a slightly different label, so treated as low confidence for uniquely distinguishing which physical unit this is.
      https://sethsparts.com/parts/352/

- [ ] **sonos mount** (id 1094) — guessed: *Sonos speaker wall mount bracket (generic/third-party accessory; official Sonos mounts also exist for specific models)* (low)
      Why uncertain: Sonos sells official wall mounts for specific speaker models, and third parties (Flexson, SANUS, Mount-It!) sell compatible brackets too; with no speaker model specified in the label, it's not possible to identify one specific mount.
      https://sethsparts.com/parts/1094/

- [ ] **stepper motor** (id 942) — guessed: *Generic stepper motor (unspecified size/type)* (low)
      Why uncertain: No size or spec given in the label, and this is a separate inventory entry from item 822 ('stepper motor nema 17'), so it's likely a different motor whose exact type cannot be determined.
      https://sethsparts.com/parts/942/

- [ ] **stepper motor mount bracket** (id 176) — guessed: *Generic NEMA 17 stepper motor mounting bracket (commodity accessory, sold under many brands)* (low)
      Why uncertain: This is an accessory/mounting hardware item, not a specific electronic product; sold under many brands (StepperOnline, Weideer, generic Amazon listings) and also widely available as a 3D-printable design, so no single canonical product applies.
      https://sethsparts.com/parts/176/

- [ ] **stepper motor nema 17** (id 822) — guessed: *NEMA 17 stepper motor (standard motor frame size/type, not one branded product)* (medium)
      Why uncertain: Per the hint, treated as a standard motor size/type rather than a single manufacturer SKU; StepperOnline is one of the most common suppliers of this exact form factor, used here only as a representative reference.
      https://sethsparts.com/parts/822/

- [ ] **teensy din board** (id 281) — guessed: *Teensy paired with a third-party MIDI DIN breakout/adapter (e.g. Deftaudio's Teensy MIDI Breakout board)* (low)
      Why uncertain: No single canonical manufacturer; Deftaudio (Tindie) and ProtoSupplies both sell small-batch Teensy MIDI DIN breakout boards, and many hobbyists also build one-off DIY versions from the classic MIDI optoisolator circuit, so the exact physical item can't be pinned down.
      https://sethsparts.com/parts/281/

- [ ] **tft displays** (id 257) — guessed: *Generic small TFT LCD display module(s) (commodity item, plural/unspecified — e.g. 1.8in SPI TFT with ST7735 driver)* (low)
      Why uncertain: Label is a vague plural ('tft displays') with no size, resolution, or interface given; used Adafruit's well-documented 1.8in ST7735R display purely as a representative example of the category, not as a confirmed match.
      https://sethsparts.com/parts/257/

- [ ] **usb host shield** (id 499) — guessed: *USB Host Shield 2.0 for Arduino (commodity item; originally by Circuits@Home, now widely cloned)* (medium)
      Why uncertain: The original design and library are from Circuits@Home; the board itself is now sold by many vendors as a near-identical clone, so there is no single current canonical manufacturer page (circuitsathome.com's own store page returned a server error when checked).
      https://sethsparts.com/parts/499/

## Section 2 — Needs your input (too ambiguous to research from the label alone)

242 items across 50 containers/drawers. Walk through each location and jot down what each item actually is (brand/model, or enough detail to look it up) — then I can run a follow-up enrichment pass.

### Container #36
- [ ] **keyboards** (qty 6.0) — id 8

### Container #38 / drawer a1
- [ ] **high speed servo** (qty 1.0) — id 509
- [ ] **jumbo led segment display** (qty 6.0) — id 498
- [ ] **load cell amp board** (qty 1.0) — id 493
- [ ] **micro servo** (qty 2.0) — id 508
- [ ] **nrf wireless modules** (qty 7.0) — id 492
- [ ] **panel mount circuit breaker** (qty 1.0) — id 496
- [ ] **photon board** (qty 2.0) — id 513
- [ ] **photon power board** (qty 1.0) — id 514
- [ ] **solid state relay** (qty 1.0) — id 502
- [ ] **sparkfun sm700 pyXY board** (qty 1.0) — id 511
- [ ] **step motor** (qty 8.0) — id 507
- [ ] **ulog board** (qty 1.0) — id 500

### Container #38 / drawer a2
- [ ] **weight sensors** (qty 10 aprox) — id 547

### Container #38 / drawer a3
- [ ] **bluerx board** (qty 1.0) — id 364
- [ ] **easydriver motor controller** (qty 8.0) — id 188
- [ ] **fan controller board** (qty 1.0) — id 303
- [ ] **microusb charger board** (qty 1.0) — id 357
- [ ] **perma-proto boards** (qty 5.0) — id 336
- [ ] **perma-proto boards with jacks** (qty 1.0) — id 343
- [ ] **pogo pin cable** (qty 1.0) — id 358
- [ ] **powerboost 1000 board** (qty 1.0) — id 355
- [ ] **proto boards** (qty 25 aprox) — id 345
- [ ] **single relay** (qty 1.0) — id 325
- [ ] **usb power breakout** (qty 1.0) — id 354

### Container #38 / drawer a4
- [ ] **12v usb adapter** (qty 1.0) — id 462
- [ ] **24v relay** (qty 1.0) — id 469
- [ ] **bonsai buckaroo board** (qty 1.0) — id 466
- [ ] **breadboard** (qty 2.0) — id 489
- [ ] **diodes** (qty 10.0) — id 474
- [ ] **jst thermal camera** (qty 1.0) — id 467
- [ ] **opto 22 solid state relay** (qty 1.0) — id 468
- [ ] **power regulator diodes** (qty 10.0) — id 482
- [ ] **usb breakout** (qty 2.0) — id 313
- [ ] **wire snap connector** (qty 1.0) — id 490
- [ ] **xt90 power connector** (qty 1.0) — id 456

### Container #38 / drawer a5
- [ ] **12v relay** (qty 1.0) — id 232
- [ ] **protosnap lilypad plus board** (qty 1.0) — id 439
- [ ] **rfduino adapter boards** (qty 8.0) — id 440
- [ ] **servo gear** (qty 35 aprox) — id 437
- [ ] **servos** (qty 3.0) — id 438
- [ ] **xbee and screen on proto board** (qty 1.0) — id 450

### Container #38 / drawer a6
- [ ] **bus pirate 3.6 board** (qty 1.0) — id 372
- [ ] **capacative touch controller board** (qty 1.0) — id 375
- [ ] **femtoduino board** (qty 2.0) — id 381
- [ ] **google environmental sensor board** (qty 1.0) — id 383
- [ ] **led lamp** (qty 2.0) — id 406
- [ ] **motenio r4 board** (qty 2.0) — id 380
- [ ] **protoboard** (qty 1.0) — id 384
- [ ] **small motor** (qty 1.0) — id 367
- [ ] **usb breakout cables** (qty 3.0) — id 371
- [ ] **vibe motor** (qty 1.0) — id 366
- [ ] **wireless charge module** (qty 1.0) — id 398
- [ ] **wireless charge rings** (qty 2.0) — id 397

### Container #38 / drawer a7
- [ ] **photoresistors** (qty 10.0) — id 617

### Container #38 / drawer a8
- [ ] **battery holder** (qty 6.0) — id 427
- [ ] **ic adapter boards** (qty 12.0) — id 428
- [ ] **ide cable** (qty 1.0) — id 420
- [ ] **intel galileo board** (qty 1.0) — id 422
- [ ] **power supply tester** (qty 1.0) — id 407
- [ ] **small cable** (qty 1.0) — id 412
- [ ] **switching power supply** (qty 1.0) — id 423
- [ ] **tt motor 1:48** (qty 1.0) — id 429

### Container #38 / drawer a9
- [ ] **battery clip** (qty 1.0) — id 274
- [ ] **camera boards** (qty 4.0) — id 273
- [ ] **fingerprint sensor** (qty 1.0) — id 282
- [ ] **float sensor** (qty 1.0) — id 278
- [ ] **gas sensor** (qty 1.0) — id 262
- [ ] **great scott great fet one board** (qty 1.0) — id 265
- [ ] **jst adapter board** (qty 1.0) — id 264
- [ ] **jst cable** (qty 1.0) — id 263
- [ ] **jst cable** (qty 1.0) — id 263
- [ ] **jst cable** (qty 1.0) — id 263
- [ ] **led bargraphs** (qty 11.0) — id 267
- [ ] **led display** (qty 1.0) — id 266
- [ ] **rotary encoder board** (qty 1.0) — id 260
- [ ] **steppers** (qty 4.0) — id 268
- [ ] **ultrasonic sensor** (qty 1.0) — id 280
- [ ] **usb micro cable** (qty 1.0) — id 185

### Container #39 / drawer b1
- [ ] **itsybitsy m4 board** (qty 1.0) — id 59
- [ ] **shelly power petering relay** (qty 1.0) — id 76
- [ ] **ultrasonic distance sensor** (qty 1.0) — id 66
- [ ] **usb power adapter** (qty 1.0) — id 69

### Container #39 / drawer b2
- [ ] **battery holders** (qty 7.0) — id 36
- [ ] **custom pcbs** (qty 3.0) — id 46
- [ ] **led fillament** (qty 6.0) — id 22
- [ ] **microswitch** (qty 3.0) — id 20
- [ ] **usb extention** (qty 1.0) — id 19
- [ ] **usb microphone** (qty 1.0) — id 47
- [ ] **usb to 3v adapter** (qty 1.0) — id 21
- [ ] **variable power supply** (qty 1.0) — id 25

### Container #39 / drawer b3
- [ ] **battery case** (qty 1.0) — id 204
- [ ] **din connector** (qty 4.0) — id 180
- [ ] **easydriver motor controller** (qty 1.0) — id 188
- [ ] **ir sensor** (qty 1.0) — id 203
- [ ] **itsybitsy m4 board** (qty 1.0) — id 59
- [ ] **jst 4 pin connector** (qty 10.0) — id 200
- [ ] **jst connector** (qty 1.0) — id 192
- [ ] **neotrellis board and buttons** (qty 1.0) — id 184
- [ ] **pcbs** (qty 4.0) — id 201
- [ ] **proximity sensor** (qty 1.0) — id 190
- [ ] **right angle optical connector** (qty 1.0) — id 194
- [ ] **usb micro cable** (qty 1.0) — id 185
- [ ] **usb to audio connector** (qty 1.0) — id 195
- [ ] **usb to ethernet connector** (qty 1.0) — id 196

### Container #39 / drawer b4
- [ ] **humidity sensor** (qty 1.0) — id 119
- [ ] **keyboard key puller and spare keys** (qty 1.0) — id 143
- [ ] **panelmount leds** (qty 10.0) — id 142
- [ ] **photoelectric proximity sensor** (qty 4.0) — id 137
- [ ] **rgb led ring** (qty 2.0) — id 123
- [ ] **rgb leds** (qty 25 aprox) — id 133
- [ ] **usb adaptor** (qty 1.0) — id 139

### Container #39 / drawer b5
- [ ] **led bargraph** (qty 1.0) — id 160
- [ ] **led cluster** (qty 1.0) — id 152
- [ ] **led string** (qty 1.0) — id 163
- [ ] **microswitch** (qty 1.0) — id 20
- [ ] **push button led square** (qty 1.0) — id 157
- [ ] **servo trigger** (qty 1.0) — id 150
- [ ] **usb c panel mount** (qty 1.0) — id 175
- [ ] **usb sata drive adapter** (qty 2.0) — id 156
- [ ] **usb sd card reader** (qty 1.0) — id 146
- [ ] **water level sensors** (qty 6.0) — id 161

### Container #39 / drawer b6
- [ ] **circuit breaker** (qty 1.0) — id 102
- [ ] **fan control board 12v** (qty 1.0) — id 105
- [ ] **splicing tool and cable cutter** (qty 1.0) — id 114
- [ ] **stepper controller** (qty 2.0) — id 115

### Container #39 / drawer b7
- [ ] **battery power switch** (qty 1.0) — id 100
- [ ] **nichrome wires** (qty 4.0) — id 93

### Container #39 / drawer b8
- [ ] **12v relay** (qty 1.0) — id 232
- [ ] **diffused led** (qty 15 aprox) — id 218
- [ ] **led light** (qty 1.0) — id 216
- [ ] **led switches** (qty 4.0) — id 211
- [ ] **panelmount led holders** (qty 4.0) — id 213
- [ ] **right angle usb adapter** (qty 1.0) — id 229
- [ ] **steel wire** (qty 1.0) — id 207

### Container #39 / drawer b9
- [ ] **din relay** (qty 2.0) — id 251
- [ ] **nema 17 stepper mount** (qty 1.0) — id 246

### Container #40 / drawer c1
- [ ] **40 to 26p adapter cable** (qty 1.0) — id 559
- [ ] **batt charger and power supply** (qty 1.0) — id 564
- [ ] **battery holder** (qty 1.0) — id 427
- [ ] **cable tv antenna adapter** (qty 5.0) — id 536
- [ ] **glink usb adapter** (qty 3.0) — id 525
- [ ] **ioio board** (qty 1.0) — id 554
- [ ] **led squares** (qty 5.0) — id 558
- [ ] **pcb test points** (qty 100.0) — id 557
- [ ] **pir motion sensor** (qty 3.0) — id 560
- [ ] **proto boards** (qty 10 aprox) — id 345
- [ ] **rgb matrix + rtc board** (qty 1.0) — id 562
- [ ] **rom upgrade boards** (qty 5.0) — id 528
- [ ] **soldering tips** (qty 9.0) — id 552
- [ ] **ultrasonic sensor** (qty 2.0) — id 280
- [ ] **ultrasonic sensor** (qty 1.0) — id 280
- [ ] **usb breakout** (qty 1.0) — id 313
- [ ] **zoomfloppy board** (qty 1.0) — id 540

### Container #40 / drawer c3
- [ ] **blufruit board** (qty 3.0) — id 285
- [ ] **fan controller board** (qty 1.0) — id 303
- [ ] **i2c soil sensor** (qty 1.0) — id 295
- [ ] **ir sensor** (qty 3.0) — id 203
- [ ] **ir sensor** (qty 3.0) — id 203
- [ ] **light/lux sensor** (qty 1.0) — id 297
- [ ] **perf/proto board** (qty 14.0) — id 301
- [ ] **piuart board** (qty 1.0) — id 302
- [ ] **pressure sensor** (qty 1.0) — id 290
- [ ] **real time clock board** (qty 1.0) — id 305
- [ ] **soil sensors** (qty 5.0) — id 284
- [ ] **solder paste kit** (qty 1.0) — id 314
- [ ] **solder wick** (qty 1.0) — id 310
- [ ] **soldering iron tips** (qty 7.0) — id 308
- [ ] **stemma qt board** (qty 1.0) — id 296
- [ ] **temperature sensor** (qty 6.0) — id 289
- [ ] **udoo board computer** (qty 1.0) — id 287
- [ ] **usb breakout** (qty 2.0) — id 313
- [ ] **water sensor** (qty 4.0) — id 319

### Container #40 / drawer c4
- [ ] **diodes** (qty 20 aprox) — id 474
- [ ] **led segments wth backpack** (qty 2.0) — id 522

### Container #40 / drawer c5
- [ ] **ir sensors** (qty 8.0) — id 572
- [ ] **multicolored leds** (qty 25 aprox) — id 570
- [ ] **panel mount leds** (qty 6.0) — id 569

### Container #40 / drawer c7
- [ ] **3300 large capacitors** (qty 2.0) — id 612

### Container #40 / drawer c8
- [ ] **3.5mm audio cable** (qty 1.0) — id 596
- [ ] **50v led plates** (qty 2.0) — id 603
- [ ] **hall effect sensors** (qty 2.0) — id 604
- [ ] **ide cable** (qty 1.0) — id 420
- [ ] **proximity sensor** (qty 2.0) — id 190
- [ ] **small jst cables** (qty 25 aprox) — id 599
- [ ] **wired headphones** (qty 2.0) — id 602

### Container #40 / drawer c9
- [ ] **leds** (qty 20.0) — id 590
- [ ] **wire wrap magentic ferules** (qty 10 aprox) — id 589
- [ ] **wireless transmitter nrf** (qty 1.0) — id 587

### Container #41
- [ ] **3800 mah battery pack** (qty 1.0) — id 628
- [ ] **usb floppy disk drive** (qty 1.0) — id 623
- [ ] **usb hub** (qty 1.0) — id 637

### Container #42
- [ ] **motorcycle chain cleaner** (qty 1.0) — id 661
- [ ] **small breadboard** (qty 1.0) — id 656
- [ ] **usb sd card reader** (qty 1.0) — id 146

### Container #48
- [ ] **wire strippers** (qty 4.0) — id 742

### Container #51
- [ ] **audio cable** (qty 1.0) — id 809
- [ ] **circuit breaker** (qty 1.0) — id 102
- [ ] **din sockets with wires** (qty 6.0) — id 828
- [ ] **microswitch** (qty 1.0) — id 20
- [ ] **network cable tester** (qty 1.0) — id 798
- [ ] **relay single channel** (qty 1.0) — id 832
- [ ] **wirecutters** (qty 1.0) — id 796
- [ ] **wirecutters** (qty 1.0) — id 796

### Container #52
- [ ] **led matrix** (qty 2.0) — id 862
- [ ] **usb c cable** (qty 1.0) — id 855

### Container #55
- [ ] **10ft insulated wire** (qty 2.0) — id 908
- [ ] **heavy duty solar panel wire** (qty 2.0) — id 895
- [ ] **led strip** (qty 1.0) — id 894

### Container #56
- [ ] **baofang wireless radio charging base** (qty 1.0) — id 919
- [ ] **power cables** (qty 6.0) — id 918

### Container #57
- [ ] **10ft 8 wire cable** (qty 1.0) — id 925
- [ ] **car cover tether wire** (qty 1.0) — id 924

### Container #59
- [ ] **wireless super nintendo controller** (qty 1.0) — id 937

### Container #60
- [ ] **6 servos mounted to base** (qty 1.0) — id 959
- [ ] **robot base platform with stepper mounted** (qty 1.0) — id 943
- [ ] **robot motor** (qty 1.0) — id 955
- [ ] **robot motor mounted to axel** (qty 1.0) — id 960

### Container #62
- [ ] **12v relay** (qty 1.0) — id 232
- [ ] **battery charger** (qty 1.0) — id 965
- [ ] **battery pack** (qty 2.0) — id 969
- [ ] **din mount bus bar relay** (qty 1.0) — id 984
- [ ] **ifixit cable holder** (qty 1.0) — id 980
- [ ] **motorcycle battery charger** (qty 1.0) — id 966
- [ ] **proximity sensors** (qty 1.0) — id 982

### Container #65
- [ ] **rigid battery charger** (qty 4.0) — id 996

### Container #66
- [ ] **c64 monitor cable** (qty 1.0) — id 1015
- [ ] **c64 power supply board** (qty 1.0) — id 1001
- [ ] **din cable** (qty 1.0) — id 1014
- [ ] **svideo to hdmi cables** (qty 1.0) — id 1012
- [ ] **usb to 3.5" floppy drive conversion** (qty 1.0) — id 1004
- [ ] **user port cable** (qty 3.0) — id 1008
- [ ] **wireless keyboard** (qty 1.0) — id 1017

### Container #68
- [ ] **40 pc 1.5 mm cable connects** (qty 4.0) — id 1043
- [ ] **breadboard wiring kit** (qty 1.0) — id 1045
- [ ] **cat5 cable 200 ft** (qty 1.0) — id 1031
- [ ] **specialized lipo battery charger** (qty 1.0) — id 1035

### Container #72
- [ ] **c64 and amiga hookup cables** (qty 30 aprox) — id 1051

### Container #73
- [ ] **wireless super nintendo controller** (qty 1.0) — id 937

### Container #80
- [ ] **power extention cables** (qty 15 aprox) — id 1071

### Container #82
- [ ] **desoldering iron** (qty 1.0) — id 1072
- [ ] **soldering iron** (qty 1.0) — id 1077
- [ ] **soldering iron tips** (qty 3.0) — id 308
- [ ] **soldering smoke absorber** (qty 1.0) — id 1075

### Container #87
- [ ] **3.5mm audio cable** (qty 1.0) — id 596
- [ ] **breadboard** (qty 1.0) — id 489
- [ ] **keyboard** (qty 1.0) — id 1099
- [ ] **keyboard key puller** (qty 1.0) — id 1112
- [ ] **led light** (qty 3.0) — id 216
- [ ] **led reel** (qty 1.0) — id 1127
- [ ] **motorcycle leather care kit** (qty 1.0) — id 1130
- [ ] **motorolla retro 3200 brick phone** (qty 3.0) — id 1126
- [ ] **perfboard** (qty 3.0) — id 1114
- [ ] **rigid power tool battery** (qty 1.0) — id 1098
- [ ] **usb barcode reader** (qty 1.0) — id 1125
- [ ] **usb c cable** (qty 3.0) — id 855
- [ ] **usb c powerswitch** (qty 1.0) — id 1132
- [ ] **usb c wall jack** (qty 1.0) — id 1131
- [ ] **usb extention cable** (qty 3.0) — id 1128
- [ ] **usb hub** (qty 1.0) — id 637
- [ ] **usb to r745 cable** (qty 1.0) — id 1129

### Container #88
- [ ] **rigid power tool battery charger** (qty 1.0) — id 1138

### Container #91
- [ ] **electric skateboard** (qty 1.0) — id 1168
- [ ] **motorcycle luggage rack** (qty 1.0) — id 1149
- [ ] **motorcycle replacement headlight bulb** (qty 1.0) — id 1154
- [ ] **motorcycle replacement seat** (qty 1.0) — id 1147
- [ ] **motorcylce original mirrors** (qty 1.0) — id 1159
- [ ] **motorcylce windscreen** (qty 1.0) — id 1148
- [ ] **motorycle maintenance log** (qty 1.0) — id 1143

### Container #98
- [ ] **battery charger** (qty 1.0) — id 965
- [ ] **wireless phone charger** (qty 2.0) — id 1180

### Container #100
- [ ] **emergency motorcycle socket set** (qty 1.0) — id 1212
- [ ] **plastic cutting board** (qty 2.0) — id 1198

### Container #105
- [ ] **small led ticker display** (qty 1.0) — id 1216
