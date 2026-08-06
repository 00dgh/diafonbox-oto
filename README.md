# DiafonBox Oto

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Multitek DiafonBox için Home Assistant entegrasyonu — **Phone ID'yi otomatik bulan** sürüm.

[@hamitdurmus](https://github.com/hamitdurmus)'un [multitek-diafonbox](https://github.com/ahamitd/multitek-diafonbox)
projesinden türetilmiştir (MIT). Kapı açma, zil sensörleri, snapshot ve olay altyapısı ona aittir;
bu çatallamanın eklediği tek şey kurulumdaki `phone_id` derdini ortadan kaldırmaktır.

[English](#english)

---

## Ne değişti

Orijinal projede kurulum için `phone_id` gerekiyordu ve onu bulmanın üç yolu vardı: iOS'ta Proxyman ile
uygulamayı proxylemek, Android'de `adb logcat | grep phone_id` çalıştırmak, ya da **kurulumu bilerek
başarısız edip Home Assistant loglarından okumak**.

Bu sürümde **sadece e-posta adresinizi giriyorsunuz.** Gerisi otomatik.

| | Önce | Şimdi |
|---|---|---|
| Kurulum girdisi | E-posta + Phone ID | Sadece e-posta |
| Phone ID nasıl bulunur | Proxyman / adb / log okuma | Otomatik |
| Birden fazla telefon | — | Listeden seçim |
| Bulunamazsa | Kurulum başarısız | Elle girişe düşer + teşhis raporu gösterir |

## Nasıl çalışıyor

`phone_id` hesabın anahtarı değil, uygulamanın kendini tanıttığı bir kimlik; hesap e-posta ile
anahtarlanıyor. Keşif bunu şöyle sömürüyor:

1. **Yoklama** — API, tek kullanımlık `phone_id` değerleriyle çağrılır (boş, sabit, sıfır-UUID).
2. **Madencilik** — dönen her gövde taranır. Sadece başarılı yanıtlar değil, **hata gövdeleri de**:
   orijinal projenin "3. Yöntem"i zaten reddedilen denemenin doğru değeri sızdırmasına dayanıyordu,
   bu onun otomatik hâli.
3. **Sıralama** — adaylar kanıt gücüne göre derecelenir: açık `phone_id` anahtarı > `phone_list`
   içindeki kimlik alanı > gövdedeki UUID > hata mesajındaki UUID. `call_id`, `location_id`, `sip`
   ve `token` gibi UUID'ye benzeyen ama başka şey olan alanlar bir kara listeyle elenir.
4. **Doğrulama** — her aday gerçekten denenir.
5. **Negatif kontrol** — kasten uydurma bir `phone_id` de denenir. O da kabul ediliyorsa sunucu bu
   alanı zaten yok sayıyor demektir; bu durumda "çalıştı" bir kanıt değildir ve sıralama yalnızca
   kanıt gücüne göre yapılır. Bu olmadan keşif kendini kandırır.

Her adımda ne denendiği ve ne bulunduğu bir rapora yazılır; rapor hem log'a hem de gerekirse
kurulum ekranına düşer. Yani başarısız olursa **neden** başarısız olduğu elinizde kalır.

### Yazma uçlarına dokunulmaz

Yoklama yalnızca okuma uçlarını kullanır: `getAccount`, `getUserLocations`, `getCallAllRecords`,
`userAccountControl`. `resumeApp` **bilerek dışarıda bırakılmıştır** — o uç oturumun push token'larını
yeniden kaydeder, boş değerlerle yoklamak telefonunuzun bildirim kaydını bozabilirdi. Bu kural bir
testle korunuyor (`test_discovery_never_calls_write_endpoints`).

## Durum — canlı test bulgusu (2026-08, dürüst uyarı)

Keşif mantığı **çevrimdışı olarak test edildi** (14 test, sentetik API gövdeleriyle). Sonra **canlı
API'ye** (`cloud.multitek.com.tr`) karşı çalıştırıldı ve önemli bir sınır ortaya çıktı:

> **E-postadan tek başına `phone_id` türetmek bu API'de mümkün görünmüyor.** `getAccount`, denenen her
> sahte `phone_id` için HTTP 200 ama **boş gövde** döndürüyor; `getUserLocations` boş liste,
> `userAccountControl` "0" veriyor. Yani gerçek, cihaza-kayıtlı bir `phone_id` olmadan hiçbir hesap
> verisi geri gelmiyor. `getAccount` e-posta ile değil, **`phone_id` ile anahtarlanıyor** gibi
> duruyor. (E-posta + şifreyle giriş yolu da denendi: `userAccountControl` yine "0" döndürüyor, ayrı
> bir `login`/`userLogin` ucu yok — 404.)

Bunun pratik sonucu: bu çatallamanın vaadi olan "sadece e-posta gir" akışı, API mevcut hâliyle buna
izin vermediği için **tek başına yeterli değil.** `phone_id` hâlâ cihazdan (Proxyman / adb) alınmalı.

Kod bu gerçeğe göre **dürüstçe davranıyor**: keşif yine de denenir (zararı yok, salt-okunur), ama
başarısız olduğunda artık "telefonu aç" demez — durumu adıyla söyler ve **elle giriş** adımına düşer.
Elle giriş ekranı upstream'in Proxyman/adb yöntemini içerir. Yani entegrasyon çalışır; sadece
`phone_id`'yi otomatik bulma hedefi bu API'de (henüz) ulaşılamaz.

Açık kalan tek umut: `phone_id` istemci tarafında üretiliyorsa, onu *keşfetmek* yerine hesaba *kaydetmek*
mümkün olabilir — ama bu, çalışan bir kimlik-doğrulama yolu gerektirir ve gözlemlenen davranış (giriş
ucunun "0" dönmesi) bunu şimdilik desteklemiyor. Gerçek hesap e-postası netleşince yeniden bakılacak.

Gerçek bir hesabınız varsa teşhisi kendiniz görebilirsiniz (salt-okunur, hesabınızda hiçbir şey
değiştirmez):

```bash
pip install aiohttp
python tools/discover_phone_id.py sizin@eposta.com
```

## Kurulum

### HACS

1. HACS > Integrations > ⋮ > Custom repositories
2. URL: `https://github.com/00dgh/diafonbox-oto` · Category: Integration
3. "DiafonBox Oto" arayıp yükleyin, Home Assistant'ı yeniden başlatın

### Manuel

`custom_components/diafonbox_oto` klasörünü Home Assistant'ın `config/custom_components/` dizinine
kopyalayıp yeniden başlatın.

### Yapılandırma

Ayarlar > Cihazlar ve Servisler > **+ Entegrasyon Ekle** > "DiafonBox Oto" > **e-postanızı girin**.

Hesapta birden fazla telefon kayıtlıysa bir seçim ekranı gelir (doğrulanmış olanlar ✓ ile işaretli).
Hiçbiri bulunamazsa elle giriş ekranına düşer ve keşif raporu orada gösterilir.

> **Not:** entegrasyon kimliği (domain) `multitek_diafonbox` değil **`diafonbox_oto`**. Orijinal
> entegrasyonun yerine geçmez, yanına kurulur. İkisi birden kuruluysa önce eskisini kaldırın.

## Entity'ler

| Tür | Entity |
|---|---|
| Lock | `lock.{konum}_kapi` |
| Binary sensor | `binary_sensor.{konum}_apartman_zili`, `binary_sensor.{konum}_daire_zili` |
| Camera | `camera.{konum}_son_zil_goruntusu` |
| Sensor | `sensor.{konum}_son_zil_zamani`, `sensor.{konum}_bugun_zil_sayisi`, `sensor.{konum}_toplam_arama` |

## Olaylar

`diafonbox_oto_doorbell_pressed` ve `diafonbox_oto_door_opened`.

```yaml
automation:
  - alias: "Kapı Zili Bildirimi"
    trigger:
      - platform: event
        event_type: diafonbox_oto_doorbell_pressed
    action:
      - service: notify.mobile_app_iphone
        data:
          title: "🔔 Kapı Zili"
          message: "Birisi kapınızı çalıyor!"
          data:
            image: "{{ state_attr('camera.seran_home_son_zil_goruntusu', 'entity_picture') }}"
```

## Testler

```bash
python tests/test_discovery.py     # veya: pytest tests/
```

Ne Home Assistant ne de ağ gerektirir.

## Bilinen sınırlamalar

- **Bulut bağımlıdır.** Her şey `cloud.multitek.com.tr` üzerinden gider; yerel API yoktur. Multitek
  sunucusu kapalıysa entegrasyon da çalışmaz.
- **Görüntü snapshot'tır**, canlı akış değil.
- `const.py` üreticinin paylaşımlı HTTP Basic kimlik bilgilerini içerir. Bunlar bu projeye ait
  değildir, orijinal projede de açıkça bulunmaktadır ve API'nin çalışması için gereklidir.
- Pushy `auth` anahtarı hâlâ sabit kodludur (orijinalden devralınan `TODO`).

---

## <a name="english"></a>English

Home Assistant integration for Multitek DiafonBox, with **automatic Phone ID discovery**.

Derived from [multitek-diafonbox](https://github.com/ahamitd/multitek-diafonbox) by
[@hamitdurmus](https://github.com/hamitdurmus) (MIT). All device functionality is theirs; this fork
only removes the Phone ID hurdle at setup.

**Before:** find `phone_id` by proxying the iOS app with Proxyman, running `adb logcat | grep phone_id`,
or deliberately failing setup and reading it out of the Home Assistant log.
**Now:** type your e-mail address.

Discovery probes the API with throwaway `phone_id` values, mines every response body — successes *and*
rejections — for identifiers, ranks them by evidence strength, then verifies each one. A negative
control (a deliberately bogus id) detects servers that ignore the field, so discovery cannot fool
itself. Only read-only endpoints are contacted; `resumeApp` is excluded because it would re-register
your phone's push tokens.

**Status (live-tested, 2026-08):** the logic passes 14 offline tests, and was run against the live
`cloud.multitek.com.tr` API. That run revealed a hard limit: **`phone_id` cannot be derived from the
e-mail alone.** `getAccount` returns an empty 200 body for any throwaway `phone_id`, so no account
data comes back without a real, device-registered `phone_id`; it appears keyed by `phone_id`, not by
e-mail. An e-mail+password login path was also tried and does not return account data either. So the
"just type your e-mail" goal is not reachable against the current API, and the manual `phone_id` route
(Proxyman/adb) is still required. Discovery still runs and degrades gracefully to manual entry with a
named diagnosis instead of a dead end.

Integration domain is `diafonbox_oto`; it installs alongside the original rather than upgrading it.

## Lisans / License

MIT — see [LICENSE](LICENSE). Original work © 2026 Hamit Durmuş.
