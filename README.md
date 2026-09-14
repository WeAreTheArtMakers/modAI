# MODAI 3.4

> **Depo durumu:** Bu ilk yayın yalnızca proje tanımı ve teknik yol haritasıdır.
> Kaynak kod, yerel macOS/M1 doğrulaması ve kullanıcı onayından sonra ayrıca
> yayımlanacaktır.

**MODAI, bir girişimcinin veya yazılım ekibinin araştırma, planlama, üretim, eleştiri,
test ve doğrulama işlerini tek terminalden yöneten local-first ajan orkestratörüdür.**
M1 Pro / 16 GB için tasarlanmıştır ve bütün uzman ajanlar aynı yerel Ollama modelini
paylaşır. Ajan sayısı model kopyası sayısı değildir: bir “ajan ordusu” farklı uzman
rolleriyle çalışırken bellekte yalnızca tek model tutulur.

Temel yaklaşım:

```text
Sizin göreviniz
      ↓
Baş orkestratör → uzman ekip → kırmızı takım → düzeltme → kalite kapıları
      ↓
Kanıtlanmış dosyalar, testler, kaynaklar ve nihai sonuç
```

Model girdileri ve proje dosyaları yerel makinede kalır. İnternet araştırması açıksa
yalnızca arama sorguları ve ajanların açtığı web adresleri dış ağa gönderilir. Tamamen
çevrimdışı çalışmak için ana ekrandan interneti kapatın veya `--no-internet` kullanın.

## İçindekiler

- [Sistem gereksinimleri](#sistem-gereksinimleri)
- [Kurulum ve kaldırma](#kurulum-ve-kaldırma)
- [Hızlı başlangıç](#hızlı-başlangıç)
- [Ana merkez ve klavye kullanımı](#ana-merkez-ve-klavye-kullanımı)
- [Görev promptu düzenleyicisi](#görev-promptu-düzenleyicisi)
- [Görev çalışma biçimi](#görev-çalışma-biçimi)
- [Orkestrasyon profilleri ve ayarlar](#orkestrasyon-profilleri)
- [Donanım analizi ve model seçimi](#donanım-analizi-ve-model-seçimi)
- [Görsel ve asset görevleri](#görsel-ve-asset-görevleri)
- [Komut satırı seçenekleri](#komut-satırı-seçenekleri)
- [Komut ekranı](#komut-ekranı)
- [Uzun görevler ve devam ettirme](#uzun-görevler-ve-devam-ettirme)
- [Yerel-öncelikli hibrit bulut](#yerel-öncelikli-hibrit-bulut-kullanımı)
- [Güvenlik modeli](#güvenlik-sınırları)
- [Testler ve sorun giderme](#testler)

## Sistem gereksinimleri

- macOS 14 Sonoma veya üzeri; Apple Silicon önerilir. Terminal arayüzü POSIX TTY kullandığı
  için Linux üzerinde de çalışabilir, ancak bu sürüm öncelikle macOS/M1 Pro üzerinde
  doğrulanmıştır.
- Python `3.10+`; çalışan `venv`, `pip` ve `pyexpat` modülleri.
- Kurulu ve çalışan [Ollama](https://ollama.com/download).
- Model ve proje için yeterli boş disk alanı.
- İnternet araştırması veya bulut sağlayıcıları kullanılacaksa ağ bağlantısı.

M1 Pro 16 GB için aynı anda yalnızca bir yerel model yüklenmesi hedeflenir. Mantıksal
ajan sayısı, RAM'de o kadar model kopyası tutulduğu anlamına gelmez.

## Kurulum ve kaldırma

Kaynak kod kullanıcı onayından sonra yayımlandığında ilk kurulum:

```bash
git clone https://github.com/WeAreTheArtMakers/modAI.git
cd modAI
./setup.sh
```

`setup.sh` şu işlemleri yapar:

1. Ollama ve Python gereksinimlerini kontrol eder.
2. İşletim sistemi, mimari, toplam bellek ve mantıksal çekirdek sayısını analiz eder.
3. Belleğe güvenli biçimde sığan, araç çağırabilen Ollama taban modelini önerir ve
   gerekirse indirir.
4. [`Modelfile`](Modelfile) üzerinden seçilen tabanla `mod-agent:latest` oluşturur.
5. `.venv` sanal ortamını yeniden oluşturur ve Python bağımlılıklarını kurar.
6. Otomatik testleri çalıştırır.
7. `~/.local/bin/modai` global başlatıcı bağlantısını kurar.

Otomatik öneriyi kurulum sırasında geçersiz kılmak mümkündür:

```bash
MODAI_BASE_MODEL=qwen3.5:4b ./setup.sh
```

`~/.local/bin` PATH içinde değilse `~/.zprofile` dosyanıza şunu ekleyin ve yeni bir
terminal açın:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Yalnızca global komutu yeniden bağlamak için:

```bash
./install-command.sh
```

Uygulamanın sanal ortamını ve global komutunu kaldırmak isterseniz uygulama kapalıyken
`~/.local/bin/modai` bağlantısını ve proje içindeki `.venv` klasörünü kaldırabilirsiniz.
Ollama modeli ayrıca tutulur; istemiyorsanız `ollama rm mod-agent` komutuyla ayrı olarak
kaldırılır. Proje ve geçmiş koşu kayıtlarını silmek bağımsız bir işlemdir.

## Hızlı başlangıç

Ollama uygulamasını açın, sonra:

```bash
cd /Users/bg/Desktop/mod-agent
./setup.sh
./run.sh
```

Kurulum `~/.local/bin/modai` komutunu da oluşturur. Bundan sonra herhangi bir proje
klasöründe yalnızca:

```bash
cd /proje/klasoru
modai
```

yazmak yeterlidir. `modai` çağrıldığı klasörü otomatik workspace yapar. `./run.sh`
ile doğrudan çağrı ise `config.json` içindeki workspace davranışını korur. Yalnızca
global komutu tekrar kurmak için `./install-command.sh` kullanılabilir.

## Ana merkez ve klavye kullanımı

`./run.sh` ok tuşlarıyla kullanılan MODAI ana merkezini açar. macOS Terminal,
iTerm2 ve benzeri terminallerin gönderdiği hem CSI hem SS3 ok dizileri desteklenir:

```text
  ███╗   ███╗ ██████╗ ██████╗   █████╗ ██╗
  ████╗ ████║██╔═══██╗██╔══██╗ ██╔══██╗██║
  ██╔████╔██║██║   ██║██║  ██║ ███████║██║
  ██║╚██╔╝██║██║   ██║██║  ██║ ██╔══██║██║
  ██║ ╚═╝ ██║╚██████╔╝██████╔╝ ██║  ██║██║
  ╚═╝     ╚═╝ ╚═════╝ ╚═════╝  ╚═╝  ╚═╝╚═╝
  YEREL AJAN ORKESTRASYONU

  ❯ Yeni görev başlat
    Çalışma klasörü seç
    Göreve devam et
    Model seç
    Orkestrasyon profili
    Komut ekranı
    Sistem durumu
    Bulut modeli
    Türkçe / English
    Çıkış
```

`↑`/`↓` ile gezin, `Enter` veya `→` ile açın, `q`, `Esc` veya `←` ile geri dönün.
`j`/`k` aşağı-yukarı, `h`/`l` geri-aç kısayolları olarak da kullanılabilir. Seçim
listenin sonunda tekrar başa, başında tekrar sona döner. Klasör seçici de yalnızca
ok tuşlarıyla dizinler arasında gezebilir.

| Ana merkez seçeneği | Ne yapar? |
|---|---|
| Yeni görev başlat | Prompt düzenleyiciyi, yazma yetkisi seçimini ve gerekiyorsa veri yönlendirme seçimini açar. |
| Çalışma klasörü seç | Ajanların okuyup yazabileceği workspace'i ok tuşlarıyla seçtirir. |
| Göreve devam et | `paused`, `needs_attention`, `blocked` veya yarım kalmış koşuları listeler. |
| Model seç | Ollama'da yerel olarak kurulu modellerden aktif modeli seçer. |
| Orkestrasyon profili | Hazır profil veya kullanıcı tanımlı tur/bütçe değerlerini seçtirir. |
| Komut ekranı | Slash komutları ve doğrudan görev girişi sunar. |
| Sistem durumu | Model, workspace, ajan, tur, süre, token, internet ve bulut durumunu gösterir. |
| Bulut modeli | OpenAI, Anthropic veya Google API erişimini yapılandırır. |
| Türkçe / English | Arayüz dilini anında değiştirir. |
| Çıkış | Terminal ayarlarını geri yükleyerek MODAI'yi kapatır. |

Terminal arayüzü tam `raw` kip yerine çıktı ayarlarını bozmayan `cbreak` giriş kipi
kullanır. Ekran her seçimde tek kare halinde ve açık `CRLF` satır sonlarıyla çizilir;
bu sayede macOS Terminal'de satırların sağa doğru kayması engellenir. Soluk metinler
terminal temasından bağımsız, okunabilir açık gri renkte gösterilir. Dar terminallerde
büyük ASCII logo otomatik olarak kompakt `MODAI` başlığına dönüşür.

## Türkçe ve English interface

Ana merkezde **Türkçe / English** satırını seçerek arayüzü oturum sırasında anında
değiştirebilirsiniz. Uygulamayı doğrudan İngilizce başlatmak için:

```bash
./run.sh --language en
MOD_AGENT_LANGUAGE=en ./run.sh
```

Kalıcı tercih için [`config.json`](config.json) içindeki `language` değerini `tr`
veya `en` yapın. Komut ekranında `/language tr` ve `/language en` de kullanılabilir.

## Görev promptu düzenleyicisi

Yeni görev ekranı terminalin basit `input()` satırı yerine MODAI'nin kendi güvenli
prompt düzenleyicisini kullanır. `←` ve `→` imleci hareket ettirir; mevcut metni
silmeden araya karakter eklenebilir. Desteklenen kısayollar:

| Tuş | İşlev |
|---|---|
| `←` / `→` | Karakter karakter hareket |
| `⌥←` / `⌥→` veya `Ctrl+←` / `Ctrl+→` | Kelime kelime hareket |
| `Home` / `End`, `Ctrl+A` / `Ctrl+E` | Başlangıç / bitiş |
| `Backspace` / `Delete` | İmlecin solu / sağı |
| `Ctrl+W` | Önceki kelimeyi sil |
| `Ctrl+U` / `Ctrl+K` | İmlecin öncesini / sonrasını sil |
| `↑` / `↓` | Bu oturumdaki önceki promptlar |
| `Enter` | Görevi gönder |
| `Esc` | İptal edip ana menüye dön |

Bracketed-paste desteklenir. Yapıştırma imlecin bulunduğu noktaya eklenir, çok satırlı
metin korunur ve durum satırında Türkçe arayüzde **Yapıştırılan metin**, İngilizce
arayüzde **Pasted text** gösterilir. Yapıştırılmış ANSI/terminal kontrol dizileri
çalıştırılmadan temizlenir. Uzun promptlar terminali taşırmak yerine yatay bir görünüm
penceresinde düzenlenir.

## Görev çalışma biçimi

Yeni görev gönderilmeden önce iki çalışma modu seçilir:

| Mod | Davranış |
|---|---|
| Uygula ve tamamla | Rol izinleri kapsamında workspace dosyaları oluşturulabilir veya değiştirilebilir; testler çalıştırılabilir. |
| Salt okunur analiz | `write_file`, `replace_in_file` ve `make_directory` araçları ajanlardan teknik olarak kaldırılır. |

Bulut yapılandırılmışsa her yeni görevde ayrıca veri yönlendirme seçimi gösterilir.
**Yalnızca yerel** varsayılandır. **Hibrit — açık araştırma** ancak o görev için
verilen açık izinle etkinleşir.

Bir yazılım görevinin olağan yaşam döngüsü şöyledir:

```text
plan → bağımlı iş paketleri → kırmızı takım tartışması → entegrasyon
     → reviewer/tester/security kapıları → düzeltme + yeniden doğrulama → final
```

Web veya dış iddia içeren işlerde `fact_checker` kapısı da eklenir. Bir kalite kapısı
`FAIL` kalırsa görev “tamamlandı” sayılmaz; checkpoint `needs_attention / blocked`
durumunda korunur. Yazma işi alan geliştirici gerçek bir dosya içeriği değişikliği
yapmadan kendi adımını tamamlayamaz.

### Etkili görev yazma

MODAI belirsiz bir isteği planlamaya çalışabilir; yine de en iyi sonuç için promptta
şu dört parçayı belirtin:

1. **Hedef:** Ortaya çıkması gereken somut sonuç.
2. **Kapsam:** İncelenecek klasörler, teknoloji veya iş alanı.
3. **Kısıtlar:** Değişmemesi gereken davranışlar, gizlilik, süre veya bağımlılık sınırı.
4. **Tamamlanma ölçütü:** Çalıştırılacak testler ve kabul kriterleri.

Kod görevi örneği:

```text
Bu klasördeki web uygulamasının mobil menü hatasını düzelt. Mevcut görsel dili ve
API sözleşmesini değiştirme. İlgili testleri ekle, lint/build çalıştır ve reviewer,
tester, security reviewer kapıları PASS olmadan tamamlandı deme.
```

İşletme araştırması örneği:

```text
Türkiye'de bağımsız tasarımcılar için abonelik ürününü değerlendir. Hedef müşteri,
rakipler, fiyatlandırma, dağıtım kanalları ve 12 aylık düşük/orta/yüksek senaryoyu
araştır. Güncel dış iddialara URL ver, varsayımları gerçeklerden ayır ve sonunda
go/no-go kararı ile ilk 30 günlük deney planını hazırla. Dosya değiştirme.
```

Mevcut projeyi tamamlama örneği:

```text
Önce mevcut dosyaları ve test komutlarını keşfet. Eksik teslimatları bir kontrol
listesine dönüştür; değişiklikleri uygula; test, build ve güvenlik kontrollerini
çalıştır. Başarısız her kapı için düzeltme yap ve kanıtları final özete ekle.
```

Parola, özel anahtar, müşteri sırrı veya üretim verisi içeren görevlerde bulutu
etkinleştirmeyin. “Dosya değiştirme”, “salt okunur” veya `--read-only` ifadeleri
yazma araçlarını kapatmak için kullanılabilir.

## Görsel ve asset görevleri

MODAI'nin metin/dosya araçları bugün şunları üretebilir:

- SVG ikon, logo, illüstrasyon ve basit placeholder;
- CSS gradient, pattern, responsive layout ve animasyon;
- erişilebilir HTML görsel alanları ve yerel font tanımları;
- projede bulunan görsel dosyalarının doğru bağlandığının kontrolü.

`validate_web_assets`, HTML `src`/`href` ve CSS `url(...)` referanslarını tarar;
uzak URL/data URI değerlerini atlar ve eksik yerel dosyaları `PASS/FAIL` JSON kaydıyla
raporlar. Referans verilmeyen boş bir `assets` klasörü tek başına hata değildir;
referans verilen ama bulunmayan dosya gerçek hatadır.

Ollama kataloğundaki **vision** etiketi görüntü girdisini anlayabilmek anlamına gelir;
PNG/JPEG üretimi anlamına gelmez. Mevcut sürümde yerel raster image-generation motoru
yoktur. Fotoğraf veya raster illüstrasyon zorunluysa kullanıcı bunu kendisi sağlamalı
ya da gelecekte eklenecek yerel image provider adaptörü kullanılmalıdır. Planlanan
adaptör, yerel sağlayıcıyı varsayılan tutacak ve buluta görsel prompt göndermeden önce
ayrı açık izin isteyecektir.

## Tek model, çok uzman

Sistemde 22 farklı uzman rolü bulunur:

| Alan | Uzmanlar |
|---|---|
| Girişim ve strateji | İş stratejisti, pazar araştırmacısı, müşteri araştırmacısı, rakip analisti |
| Ürün ve işletme | Ürün yöneticisi, proje yöneticisi, operasyon yöneticisi |
| Ticari | Finans analisti, büyüme pazarlamacısı, satış stratejisti, hukuk/risk analisti |
| Yazılım | Teknik araştırmacı, veri analisti, mimar, UX uzmanı, geliştirici |
| Kalite | Kıdemli inceleyici, test mühendisi, güvenlik inceleyicisi, doğruluk denetçisi |
| Tartışma | Kırmızı takım eleştirmeni, baş entegratör |

Baş orkestratör görev için gereken rolleri seçer. Her rol bitince çıktısı diske
yazılır ve sonraki uzman gerekli özeti görür. Ardından:

1. Uzman iş paketleri bağımlılık sırasıyla yürütülür.
2. Kırmızı takım varsayımlara, çelişkilere ve kanıt boşluklarına saldırır.
3. Baş entegratör itirazları kanıtla kabul veya reddeder.
4. Web iddiaları doğruluk denetçisine gider.
5. Kod işleri inceleme, test ve güvenlik kapılarından geçer.
6. Bir kapı `FAIL` verirse geliştirici/entegratör düzeltir ve testler tekrar çalışır.
7. Sonuçlandırıcı yalnızca araç kayıtlarıyla desteklenen nihai sonucu sunar.

Varsayılan üst sınır 24 mantıksal ajan oturumudur; ayarlanabilir teknik sınır 256'dır.
Roller ve tartışma/düzeltme turları bu bütçeyi paylaşır. Tek model nedeniyle ajanlar
paralel çalışmaz ve ikinci bir model belleğe yüklenmez.

## Paralel orkestrasyon yol haritası

Mevcut sürüm M1 Pro / 16 GB üzerinde kararlı ve düşük bellekli çalışmak için görevleri
sıralı yürütür. Daha güçlü bir makinede **aynı tek modeli** kullanan bağımsız uzmanları
paralel çalıştırmak için önerilen altyapı aşağıdadır. Bu bölüm tasarım yol haritasıdır;
paralel yürütme henüz etkin değildir.

1. `execution_mode: sequential | parallel | adaptive` ve ayrı bir
   `max_concurrent_agents` ayarı eklenir. M1 Pro varsayılanı `sequential` ve `1`
   olarak kalır.
2. Planlayıcının mevcut `depends_on` alanı gerçek bir görev DAG'ına dönüştürülür.
   Bağımlılığı tamamlanan işler bir hazır kuyruğuna alınır; bağımlı işler sonuçları
   bekler.
3. Koordinatör `asyncio.TaskGroup` ve bir semaphore ile eşzamanlı istek sayısını
   sınırlar. Tüm ajanlar aynı Ollama model adını kullanır; ikinci model yüklenmez.
4. Araştırmacı, rakip analisti, doğruluk denetçisi ve salt-okunur inceleyiciler
   doğrudan paralel çalışabilir. Aynı dosyalara yazabilecek ajanlar aynı workspace'i
   paylaşmaz; her biri ayrı Git worktree/izole çalışma alanı kullanır.
5. Yazma sonuçları birleştirme kuyruğuna girer. Baş entegratör çakışmaları çözer,
   ardından test ve güvenlik kapıları birleşmiş sonuç üzerinde çalışır.
6. Durum dosyası tek bir paylaşılan JSON'u farklı süreçlerden değiştirmek yerine
   append-only olay günlüğü ve tek-yazarlı koordinatör kullanır. Böylece yarım yazma,
   kayıp güncelleme ve bozuk checkpoint riski azaltılır.
7. Her paralel işe zaman aşımı, iptal sinyali, yeniden deneme bütçesi ve bağımsız
   checkpoint eklenir. Uygulama kapansa bile yalnızca yarım kalan dallar yeniden
   çalıştırılır.
8. `adaptive` kip kullanılabilir RAM/VRAM, bağlam boyutu ve kuyruk gecikmesine göre
   eşzamanlılığı otomatik düşürür veya artırır.

Ollama tek bir model için paralel istekleri destekler; ancak gerekli bellek paralel
istek sayısı ile bağlam boyutuna bağlı olarak büyür. Bu nedenle uygulamanın ajan
semaphore değeri ile Ollama'nın `OLLAMA_NUM_PARALLEL` değeri birlikte yönetilmelidir.
Tek model garantisi için `OLLAMA_MAX_LOADED_MODELS=1` kullanılabilir. Ayrıntılar:
[Ollama FAQ – concurrent requests](https://docs.ollama.com/faq#how-does-ollama-handle-concurrent-requests).

Önerilen başlangıç profilleri:

| Makine | Yürütme | Eşzamanlı ajan | İlk bağlam önerisi |
|---|---|---:|---:|
| M1 Pro, 16 GB | sequential | 1 | 4K–8K |
| 32–64 GB Apple Silicon | adaptive | 2–4 | 8K |
| Güçlü tek GPU, yeterli VRAM | adaptive | 2–8 | modele göre ölçülmeli |
| Çok GPU / sunucu | parallel | yük testiyle belirlenir | toplam KV cache'e göre |

Bu değerler sabit performans garantisi değildir. Model boyutu ve quantization aynı
makinede güvenli eşzamanlılık düzeyini önemli ölçüde değiştirir; profil bir yerel yük
testinden sonra kaydedilmelidir.

## Orkestrasyon profilleri

Ana ekrandan seçilebilir:

| Profil | Ajan sınırı | Tartışma | Düzeltme | Aktif süre |
|---|---:|---:|---:|---:|
| Hızlı | 8 | 0 | 1 | 2 saat |
| Dengeli | 16 | 1 | 2 | 8 saat |
| Derin | 24 | 2 | 2 | 12 saat |
| Maraton | 32 | 3 | 3 | 24 saat |

Profil büyüdükçe sonucun otomatik olarak daha doğru olacağı varsayılmamalıdır. Gereksiz
ajan ve tartışma turları aynı dosyaları tekrar okuyarak süre/token tüketebilir ve eski
bulguların bağlamda kalma ihtimalini artırabilir.

| Görev örneği | Önerilen profil | M1 Pro 16 GB model |
|---|---|---|
| Tek dosya düzeltme, README, küçük CSS/HTML sorunu | `fast` | `qwen3.5:4b` veya kalite önceliğinde `qwen3.5:9b` |
| Birkaç dosyalı özellik, küçük landing page, olağan test/düzeltme | `balanced` | `qwen3.5:9b` |
| Mimari değişiklik, araştırmalı ürün işi, çok bileşenli uygulama | `deep` | `qwen3.5:9b` |
| Uzun işletme araştırması veya kullanıcı gözetimindeki çok aşamalı çalışma | `marathon` | Yerel 9B + gerekirse açık izinli hibrit araştırma |

Basit statik landing page düzeltmesi için örnek:

```bash
modai --profile balanced --max-total-tokens 250000 \
  "HTML/CSS/JS uyumsuzluklarını düzelt, yerel asset referanslarını doğrula ve test et"
```

Uzun göreve yüksek bütçe vermek zorunlu değildir. Token bütçesi bir hedef değil,
yalnızca güvenlik üst sınırıdır; kalite kapıları erken geçerse çalışma erken biter.

Profil ekranındaki **Özel ayarları düzenle** seçeneği şu değerleri terminalden
değiştirebilir ve isteğe bağlı olarak `config.json` içine kalıcı kaydedebilir:

- Toplam mantıksal ajan: `1–256`
- Tartışma turu: `0–20`
- Düzeltme turu: `0–20`
- Ajan başına araç turu: `1–50`
- Hata sonrası yeniden deneme: `0–10`
- Aktif çalışma süresi: `0.1–168` saat
- Toplam input+output token bütçesi: `1000–10000000`

Komut ekranında tek bir değer de değiştirilebilir:

```text
/set debate_rounds 6
/set repair_rounds 8
/set max_agents 80
/set max_total_tokens 750000
```

Bu üst sınırlar yanlışlıkla sonsuz döngü oluşturmayı engeller; yüksek bir değer
seçmek tüm turların mutlaka kullanılacağı anlamına gelmez.

### Ayarların anlamı ve önceliği

| Ayar | Varsayılan | Aralık | Açıklama |
|---|---:|---:|---|
| `model` | `mod-agent:latest` | metin | Tek aktif yerel Ollama modeli. |
| `host` | `127.0.0.1:11434` | yalnızca localhost | Yerel Ollama adresi; uzak host reddedilir. |
| `context_size` | `8192` | `2048–131072` | Tek model isteğinin bağlam penceresi. |
| `temperature` | `0.25` | `0–2` | Üretim çeşitliliği. Kod için düşük değer önerilir. |
| `workspace` | `./workspace` | klasör | `./run.sh` ile açılışta kullanılacak çalışma klasörü. |
| `max_agents` | `24` | `1–256` | İş paketi, tartışma, kalite ve düzeltmelerin ortak oturum bütçesi. |
| `debate_rounds` | `2` | `0–20` | Eleştirmen + entegratör tartışma turu. |
| `repair_rounds` | `2` | `0–20` | Başarısız kalite kapıları sonrası azami düzeltme turu. |
| `max_tool_rounds` | `8` | `1–50` | Tek ajanın art arda yapabileceği araç turu. |
| `agent_retries` | `1` | `0–10` | Hata veren ajan adımının yeniden denenme sayısı. |
| `max_hours` | `12` | `0.1–168` | Model/ajanların toplam aktif çalışma süresi. |
| `max_total_tokens` | `500000` | `1000–10000000` | Koşunun toplam input+output bütçesi. |
| `internet_enabled` | `true` | boolean | Yerleşik web araştırma araçlarını açar. |
| `keep_alive` | `5m` | Ollama süresi | Modelin son istekten sonra bellekte kalma süresi. |
| `think` | `false` | boolean | Model destekliyorsa düşünme kipini geçirir. |
| `language` | `tr` | `tr`, `en` | Terminal arayüz dili. |
| `cloud_*` | kapalı | sağlayıcıya göre | Hibrit bulut yapılandırması ve rol izin listesi. |

Ayar önceliği, yüksekten düşüğe şöyledir:

1. O çalıştırmaya verilen CLI seçenekleri.
2. Ortam değişkenleri.
3. [`config.json`](config.json).
4. Kod içindeki güvenli varsayılanlar.

Ana merkezdeki özel profil düzenleyicisi değerleri yalnızca oturuma uygulayabilir veya
onay verilirse atomik biçimde `config.json` içine kaydedebilir. Komut ekranındaki
`/set` değişiklikleri yalnızca o MODAI süreci için geçerlidir.

### Ortam değişkenleri

| Değişken | Ayar |
|---|---|
| `MOD_AGENT_MODEL` | `model` |
| `MOD_AGENT_HOST` | `host` |
| `MOD_AGENT_CONTEXT_SIZE` | `context_size` |
| `MOD_AGENT_TEMPERATURE` | `temperature` |
| `MOD_AGENT_WORKSPACE` | `workspace` |
| `MOD_AGENT_MAX_AGENTS` | `max_agents` |
| `MOD_AGENT_MAX_TOOL_ROUNDS` | `max_tool_rounds` |
| `MOD_AGENT_DEBATE_ROUNDS` | `debate_rounds` |
| `MOD_AGENT_REPAIR_ROUNDS` | `repair_rounds` |
| `MOD_AGENT_MAX_HOURS` | `max_hours` |
| `MODAI_MAX_TOTAL_TOKENS` | `max_total_tokens` |
| `MOD_AGENT_AGENT_RETRIES` | `agent_retries` |
| `MOD_AGENT_INTERNET` | `internet_enabled` |
| `MOD_AGENT_KEEP_ALIVE` | `keep_alive` |
| `MOD_AGENT_THINK` | `think` |
| `MOD_AGENT_LANGUAGE` | `language` |
| `MODAI_CLOUD_ENABLED` | `cloud_enabled` |
| `MODAI_CLOUD_PROVIDER` | `cloud_provider` |
| `MODAI_CLOUD_MODEL` | `cloud_model` |
| `MODAI_CLOUD_ROLES` | Buluta aday rol izin listesi |

## Komut satırı seçenekleri

Genel biçim:

```bash
modai [SEÇENEKLER] [GÖREV]
```

`modai` global komutu, `--workspace` ayrıca verilmediyse komutun çalıştırıldığı klasörü
workspace yapar. Depo içindeki `./run.sh` ise `config.json` değerini kullanır.

| Seçenek | İşlev |
|---|---|
| `-h`, `--help` | Bütün CLI seçeneklerini gösterir. |
| `--version` | MODAI sürümünü gösterir. |
| `--model MODEL` | Bu süreçte kullanılacak yerel Ollama modelini seçer. |
| `--workspace PATH` | Çalışma klasörünü açıkça belirler. |
| `--language tr\|en` | Terminal arayüz dilini seçer. |
| `--profile fast\|balanced\|deep\|marathon` | Hazır orkestrasyon profili uygular. |
| `--max-agents N` | Mantıksal ajan/oturum bütçesini değiştirir. |
| `--debate-rounds N` | Tartışma turu sayısını değiştirir. |
| `--repair-rounds N` | Düzeltme turu sayısını değiştirir. |
| `--max-tool-rounds N` | Ajan başına araç turunu değiştirir. |
| `--agent-retries N` | Ajan adımı yeniden deneme sayısını değiştirir. |
| `--max-hours SAAT` | Aktif çalışma süresi üst sınırını değiştirir. |
| `--max-total-tokens N` | Koşunun toplam token üst sınırını değiştirir. |
| `--no-internet` | Yerleşik internet araçlarını bu süreçte kapatır. |
| `--read-only` | Yeni CLI görevinin bütün yazma araçlarını kaldırır. |
| `--allow-cloud` | Yapılandırılmış bulutu yalnızca uygun açık araştırma paketleri için etkinleştirir. |
| `--list-models` | Ollama'da kurulu modelleri listeler ve çıkar. |
| `--recommend-model` | Donanımı analiz eder, uygun yerel modeli ve güvenli fallback'i JSON gösterir. |
| `--list-runs` | Son checkpoint koşularını JSON olarak listeler ve çıkar. |
| `--resume [RUN_ID]` | Belirtilen veya en yeni devam edilebilir koşuyu sürdürür. |
| `--no-color` | ANSI renklerini kapatır. |

Yaygın örnekler:

```bash
# Bulunduğunuz projede ok tuşlu arayüz
modai

# Arayüz açmadan tek görev
modai "Testleri çalıştır, hataları düzelt ve tekrar doğrula"

# Açıkça seçilmiş workspace ve model
modai --workspace /Users/me/proje --model qwen3:8b "Projeyi incele"

# Tamamen yerel ve çevrimdışı salt-okunur analiz
modai --no-internet --read-only "Mimari ve güvenlik risklerini raporla"

# Uzun kod görevi
modai --profile marathon --max-total-tokens 1000000 "Uygula, test et ve kalite kapıları geçene kadar düzelt"

# Hibrit açık araştırma; önce /cloud setup gerekir
modai --allow-cloud "Rakipleri güncel kaynaklarla araştır ve yerel strateji raporu oluştur"
```

Kabukta çok satırlı komut yazarken ters bölü `\` satırın son karakteri olmalıdır;
önüne ayrıca `\` veya boşluk koymayın:

```bash
modai --resume 20260913-233710-921520 \
  --max-agents 32 \
  --repair-rounds 4 \
  --max-total-tokens 1500000
```

## Canlı ajan ve token görünümü

Her model isteği sırasında tek satırlık mini spinner aktif ajanı, kullanılan
sağlayıcıyı ve geçen süreyi gösterir. İstek tamamlandığında satır; input token,
output token ve görev toplamını gösteren sakin bir telemetri kaydına dönüşür.
Toplam kullanım checkpoint içindeki `usage` alanına yazılır ve devam ettirilen
görevlerde kaldığı yerden sayılır. Animasyon TTY olmayan çalıştırmalarda otomatik
olarak sade metne düşer.

Varsayılan görev bütçesi `500000` toplam input+output token'dır. Bu sınır
`max_total_tokens`, `/set max_total_tokens DEĞER` veya `MODAI_MAX_TOTAL_TOKENS`
ile `1000–10000000` arasında değiştirilebilir. Sınır aşılırsa kontrolsüz araç
döngüsüne devam etmek yerine görev checkpoint'e alınır.

## Orkestrasyon güvenilirliği

MODAI 3.4, küçük modellerin araç protokolünden sapabildiği durumlar için ek korumalar
uygular:

- Bir yanıtta XML/artık metin arasında birden fazla `{"tool":...,"args":...}`
  nesnesi varsa ayrı ayrı kurtarılıp çalıştırılır.
- Bozuk araç JSON'u normal ajan sonucu sayılmaz; modele düzeltme talebi gönderilir.
- Aynı araç ve argümanların ikiden fazla tekrarı engellenir.
- Son turda üretilen fakat çalıştırılmamış araç çağrısı başarı sayılmaz.
- Yazma görevi alan geliştirici en az bir doğrulanmış dosya içeriği değişikliği yapmadan
  `completed` olamaz.
- `make_directory` workspace dışına çıkamayan ayrı bir araçtır; shell üzerinden
  `mkdir` çağırmak gerekmez.
- Kalite kapılarından biri `FAIL` kalırsa koşu `completed` değil `needs_attention`
  ve `blocked` olarak kaydedilir. Düzeltme bütçesi artırıldıktan sonra `/resume` ile
  devam edilebilir.
- Eski bir koşu zaten geçerli token bütçesini aşmışsa devam ettirmeden önce açıkça
  yeni bir bütçe ister; gereksiz bir model çağrısı yapmaz.
- Planlayıcı, ajan bütçesinin tamamını ilk iş paketlerinde tüketmez; tartışma,
  doğrulama ve düzeltme turları için kapasite ayırır.
- Tester, reviewer, security reviewer, fact checker, critic ve integrator normal
  uygulama planına alınmaz; yalnızca kendi kalite/tartışma aşamalarında çalışır.
- Basit yazılım görevleri en fazla dört uygulama iş paketine indirilir; kalite kapıları
  bu sınırın dışında ayrılmış bütçeyle eklenir.
- HTML/CSS içindeki eksik yerel asset referansları `validate_web_assets` ile model
  yorumundan bağımsız doğrulanabilir.

## Yerel-öncelikli hibrit bulut kullanımı

Bulut kullanımı varsayılan olarak kapalıdır. Yerel model planlama, kod/dosya işleri,
birleştirme, güvenlik kontrolü ve nihai sonucu elinde tutar. Bulut yalnızca kullanıcı
ilgili görev için ayrıca **Hibrit — açık araştırma** izni verirse kullanılabilir.

Desteklenen API sağlayıcıları:

- OpenAI Responses API
- Anthropic Messages API
- Google Gemini generateContent API

Ana menüde **Bulut modeli** veya komut ekranında `/cloud setup` ile sağlayıcı, model
ve API anahtarı girilir. macOS'ta anahtar düz metin yapılandırmaya değil Keychain'e
kaydedilir. Alternatif olarak `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` veya
`GOOGLE_API_KEY` ortam değişkenleri kullanılabilir.

Web sitesi üyeliği oturumlarını taklit eden veya tarayıcı çerezlerini okuyan bir giriş
yapılmaz. Sağlayıcının desteklediği API kimlik bilgisi gerekir. OpenAI'nin resmi hızlı
başlangıç belgesi de API erişimi için bir API anahtarı oluşturulmasını ve
`OPENAI_API_KEY` kullanılmasını tarif eder:
[OpenAI API quickstart](https://developers.openai.com/api/docs/quickstart).

Veri sınırları:

1. Her yeni görevde yönlendirme seçimi yeniden sorulur; varsayılan **Yalnızca yerel**dir.
2. Yalnızca `cloud_roles` izin listesindeki ve `needs_web=true` olan araştırma paketleri
   buluta aday olabilir.
3. Bulut prompt'una workspace listesi, dosya içeriği, araç çıktıları veya önceki ajan
   konuşmaları eklenmez.
4. API anahtarı/private-key gibi belirgin sır örüntüsü algılanırsa paket yerel modele
   döner.
5. Bulut isteği başarısızsa orkestrasyon bozulmaz; aynı iş yerel modelle sürdürülür.

İş stratejisi gibi bağlama bağlı ticari sırlar otomatik regex ile kusursuz biçimde
tespit edilemez. Bu yüzden gizli görevlerde hibrit moda kullanıcı tarafından da izin
verilmemelidir.

Komut satırından:

```bash
./run.sh --profile deep --workspace /tam/proje/yolu "Ürünü incele, geliştir ve test et"
./run.sh --profile marathon --max-hours 24 "Girişim planını araştır ve doğrula"
./run.sh --max-agents 32 --debate-rounds 3 --repair-rounds 4 --max-total-tokens 750000 "Görev"
```

`max_hours` yalnızca aktif model/ajan çalışma süresini sayar. Yapılandırmadaki üst
sınır 168 saattir.

## Uzun görevler ve devam ettirme

Her plan, ajan, araç çağrısı, tartışma ve kalite kapısından sonra atomik checkpoint
`memory/runs/<koşu-id>/state.json` dosyasına yazılır. `Ctrl+C`, süre sınırı veya hata
sonrasında görev kaldığı adımdan devam ettirilebilir:

```bash
./run.sh --list-runs
./run.sh --resume
./run.sh --resume 20260913-221012-991745
./run.sh --resume 20260913-221012-991745 --max-total-tokens 1500000 --repair-rounds 4
```

Ok tuşlu ana ekrandaki **Göreve devam et** seçeneği de duraklatılmış koşuları listeler.

### Koşu durumları

| Durum | Anlamı | Kullanıcı eylemi |
|---|---|---|
| `running` | Görev çalışıyor veya süreç beklenmedik biçimde kapandığı için son checkpoint bu durumda kaldı. | Aktif süreç yoksa `/resume RUN_ID`. |
| `paused` | `Ctrl+C`, süre veya token sınırı nedeniyle güvenli checkpoint alındı. | Sınırı gerekiyorsa artırıp devam edin. |
| `needs_attention` / `blocked` | Kalite kapılarından en az biri hâlâ `FAIL`. | Ajan/düzeltme/token bütçesini artırıp devam edin veya gereksinimi netleştirin. |
| `completed` | Son kalite kapıları geçti ve final yanıt üretildi. | Sonucu ve workspace değişikliklerini gözden geçirin. |
| `failed` | Bir adım yeniden denemelerden sonra tamamlanamadı. | Hata kaydını inceleyin ve koşuyu sürdürün. |

Eski sürümlerin `FAIL` kalite kapıları olmasına rağmen `completed` yazdığı koşular,
listeleme sırasında otomatik olarak `needs_attention / blocked` kabul edilir.

### Checkpoint dosyaları

```text
memory/runs/<RUN_ID>/
├── state.json   # plan, faz, ajan çıktıları, kullanım ve araç kanıtları
└── final.txt    # final aşamasına ulaşılmışsa kullanıcı özeti
```

`state.json` içindeki `usage` alanı input token, output token, toplam istek ve bulut
isteği sayaçlarını taşır. Devam ettirme bu sayaçları sıfırlamaz. Önceki kullanım yeni
`max_total_tokens` değerine ulaşmışsa MODAI pahalı bir model çağrısı yapmadan önce
bütçenin artırılmasını ister.

Örnek kurtarma:

```bash
modai --list-runs
modai --resume RUN_ID --max-agents 32 --repair-rounds 4 --max-total-tokens 1500000
```

`max_agents`, planlanan ilk işlerden final aşamasına kadar bütün mantıksal oturumların
ortak bütçesidir. Eski bir koşuda çok sayıda çıktı varsa yalnızca `repair_rounds`
artırmak yetmeyebilir; yeniden doğrulama ajanları için `max_agents` da artırılmalıdır.

### Güvenli durdurma

Çalışan görev `Ctrl+C` ile durdurulabilir. MODAI mevcut checkpoint'i `paused` olarak
kaydeder ve terminal giriş kipini geri yükler. Süreci zorla kapatmak atomik durum
dosyasını genellikle korusa da normal `Ctrl+C` yolu tercih edilmelidir. Aynı koşuyu
iki ayrı MODAI sürecinde eşzamanlı olarak devam ettirmeyin.

## Çalışma klasörü

Ana ekrandaki klasör tarayıcısıyla herhangi bir proje klasörü seçilebilir. Alternatif:

```bash
./run.sh --workspace /Users/bg/Projects/my-app "testleri çalıştır ve hataları düzelt"
```

Dosya araçları seçilen klasörün dışına çıkamaz. Büyük klasörler (`node_modules`,
`.git`, `.venv`, `dist`, `build`) taramalarda atlanır.

Yeni görev ekranında iki yetki modu vardır:

- **Uygula ve tamamla:** ajanlar gerektiğinde dosya yazabilir.
- **Salt okunur analiz:** yazma araçları teknik olarak ajanlardan kaldırılır.

Tek seferlik salt-okunur kullanım:

```bash
./run.sh --read-only --workspace /proje "mimariyi eleştir"
```

## Donanım analizi ve model seçimi

MODAI kurulumu seri numarası, kullanıcı dosyaları veya kişisel veri okumadan yalnızca
işletim sistemi, CPU mimarisi/çip adı, toplam bellek ve mantıksal çekirdek sayısını
inceler. Öneriyi istediğiniz zaman görebilirsiniz:

```bash
modai --recommend-model
```

Komut ekranında `/recommend-model`, ana merkezde **Sistem durumu** ve **Model seç**
ekranları da donanıma uygun modeli gösterir. Kurulu modelleri ve aktif modeli görmek:

```bash
modai --list-models
```

### M1 Pro 16 GB önerisi

14 Eylül 2026 tarihinde resmî Ollama kataloğu ve bu makinedeki gerçek çalışma ölçümü
birlikte değerlendirildi:

| Model | İndirme boyutu | Ollama yetenekleri | M1 Pro 16 GB kararı |
|---|---:|---|---|
| `qwen3.5:4b` | 3,4 GB | tools, thinking, vision | En hızlı fallback; basit işler ve düşük bellek baskısı. |
| `qwen3.5:9b` | 6,6 GB | tools, thinking, vision | **Önerilen dengeli varsayılan.** |
| `qwen3.5:9b-mlx` | 8,9 GB | tools, thinking, vision | Çalışır; yerel 8K testinde toplam çalışma alanı 17 GB'a ulaştığı için varsayılan değil. |
| `gemma3:12b` | 8,1 GB | vision | Genel üretim güçlü olabilir; resmî katalogda tools etiketi olmadığı için ajan varsayılanı değil. |
| `gpt-oss:20b` | 14 GB | tools, thinking | Ollama 16 GB'ta çalışabildiğini belirtiyor; uzun bağlam/OS payı için çok dar. |
| `qwen3-coder:30b` | 19 GB | tools, 256K context | 16 GB'a sığmaz; 32 GB+ kod ağırlıklı sistemler için. |

Bu nedenle M1 Pro 16 GB için seçilen politika:

```text
taban model       qwen3.5:9b
MODAI modeli      mod-agent:latest
bağlam            8192
yerel model       aynı anda 1
paralel istek     1
basit görev       fast veya balanced profil
uzun/kritik görev deep; yalnızca gerçekten gerekliyse marathon
```

Bu öneri bir çıkarımdır: Ollama katalog boyutları, araç yeteneği ve bu cihazdaki
ölçülen bellek davranışı birlikte kullanılmıştır. Ollama, 24 GiB altı GPU belleğinde
varsayılan bağlamı 4K seçer ve daha geniş bağlamın daha fazla bellek gerektirdiğini
belirtir. MODAI çok ajanlı araç promptları için 8K kullanır; bellek baskısında 4K ve
`qwen3.5:4b` güvenli geri dönüş yoludur.

Resmî kaynaklar:

- [Ollama Qwen 3.5 model ailesi](https://ollama.com/library/qwen3.5)
- [Ollama Qwen3-Coder model ailesi](https://ollama.com/library/qwen3-coder)
- [Ollama gpt-oss model ailesi](https://ollama.com/library/gpt-oss)
- [Ollama Gemma 3 model ailesi](https://ollama.com/library/gemma3)
- [Ollama context length ve bellek açıklaması](https://docs.ollama.com/context-length)
- [Ollama tool-calling/ajan döngüsü](https://docs.ollama.com/capabilities/tool-calling)
- [Ollama paralellik ve bellek FAQ](https://docs.ollama.com/faq)

### Modeli elle değiştirme

Model mimariden bağımsızdır. Bir modeli önce Ollama'ya indirin, sonra MODAI'ye verin:

```bash
ollama pull qwen3.5:4b
modai --model qwen3.5:4b
MOD_AGENT_MODEL=qwen3.5:4b modai
```

Kalıcı varsayılan [`config.json`](config.json) içindeki `model` satırıdır. Özel
`mod-agent:latest` modelini farklı tabanla yeniden üretmek için:

```bash
MODAI_BASE_MODEL=qwen3.5:4b ./setup.sh
```

Gizlilik için `host` yalnızca `localhost`, `127.0.0.1` veya `::1` olabilir. Uzak model
sunucuları yapılandırma doğrulamasında reddedilir.

### Model seçerken neden yalnızca parametre sayısına bakılmıyor?

Bir modelin ağırlıklarının belleğe sığması yeterli değildir. MODAI aynı anda model
ağırlıkları, KV bağlam önbelleği, macOS, terminal araçları ve proje testlerine yer
bırakmalıdır. Ollama ayrıca paralel isteklerin bağlam belleğini paralellik sayısıyla
çarptığını belirtir. Bu nedenle 16 GB profili `OLLAMA_MAX_LOADED_MODELS=1` ve
`OLLAMA_NUM_PARALLEL=1` yaklaşımını kullanır; büyük ama swap'e düşen model yerine
daha hızlı, araç uyumlu model seçilir.

## İnternet araştırması

`search_web` anahtarsız Bing araması yapar; `fetch_url` seçilen sayfayı metne çevirir.
Araştırma ajanları kaynak URL'lerini raporlar ve doğruluk denetçisi önemli iddiaları
bağımsız kontrol eder.

Tam çevrimdışı görev:

```bash
./run.sh --no-internet "yerel kodu incele"
```

Komut ekranında `/internet on` veya `/internet off` da kullanılabilir. Yerel IP,
`localhost` ve `.local` adresleri web aracı tarafından engellenir.

## Komut ekranı

Ana merkezden **Komut ekranı** seçildiğinde `sen ›` / `you ›` istemi açılır. Başında
`/` bulunmayan her metin yeni bir yerel görev olarak çalıştırılır.

| Komut | Açıklama | Örnek |
|---|---|---|
| `/help` | Kullanılabilir komutların kısa listesini gösterir. | `/help` |
| `/menu` | Komut ekranından ok tuşlu ana merkeze döner. | `/menu` |
| `/agents` | Bütün rol kimliklerini ve çevrilmiş uzman adlarını gösterir. | `/agents` |
| `/models` | Kurulu Ollama modellerini listeler; aktif model `*` ile işaretlenir. | `/models` |
| `/recommend-model` | Donanım analizi ve önerilen Ollama modelini gösterir. | `/recommend-model` |
| `/model MODEL` | Aktif modeli yalnızca bu süreç için değiştirir. | `/model qwen3:8b` |
| `/workspace PATH` | Workspace'i var olan bir klasöre değiştirir. | `/workspace /Users/me/proje` |
| `/internet on\|off` | Yerleşik web araçlarını açar veya kapatır. | `/internet off` |
| `/profile PROFİL` | `fast`, `balanced`, `deep` veya `marathon` uygular. | `/profile deep` |
| `/set AYAR DEĞER` | Ayarlanabilir bir orkestrasyon değerini bu oturumda değiştirir. | `/set repair_rounds 4` |
| `/cloud` | Bulut durumu, sağlayıcı, model, rol listesi ve politikayı gösterir. | `/cloud` |
| `/cloud setup` | Sağlayıcı/model/API anahtarı kurulumunu başlatır ve macOS Keychain'e kaydeder. | `/cloud setup` |
| `/cloud off` | Bulut yapılandırmasını kalıcı olarak devre dışı bırakır. | `/cloud off` |
| `/hybrid GÖREV` | Verilen yeni görevde uygun kamuya açık araştırma paketlerine bulut izni verir. | `/hybrid Avrupa rakiplerini araştır` |
| `/language tr\|en` | Komut ekranı dilini anında değiştirir. | `/language en` |
| `/runs` | Son koşu kimliklerini, durumlarını ve görev özetlerini gösterir. | `/runs` |
| `/resume [KOŞU_ID]` | Belirtilen veya en yeni devam edilebilir görevi checkpoint'ten sürdürür. | `/resume 20260913-233710-921520` |
| `/status` | Etkin bütün ayarları JSON biçiminde gösterir. | `/status` |
| `/clear` | Terminal ekranını temizler. | `/clear` |
| `/exit`, `/quit` | MODAI'den çıkar. `exit` ve `quit` da kabul edilir. | `/exit` |

`/set` ile düzenlenebilen değerler:

```text
max_agents
debate_rounds
repair_rounds
max_hours
max_total_tokens
max_tool_rounds
agent_retries
```

`/set`, `/model`, `/workspace`, `/internet`, `/profile` ve `/language` değişiklikleri
yalnızca çalışan süreçte geçerlidir. Özel profil ekranındaki kaydetme seçeneği ve bulut
kurulumu ise ilgili değerleri `config.json` içine kalıcı yazabilir.

## Güvenlik sınırları

### Ajan araçları

Her rol yalnızca görevine uygun araçların şemasını görür. Bir ajanın bir aracı istemesi
tek başına yeterli değildir; merkezi kayıt ayrıca rol izin listesini doğrular.

| Araç | Amaç |
|---|---|
| `list_files` | Workspace dosya ağacını, ağır/üretilmiş klasörleri atlayarak listeler. |
| `read_file` | UTF-8 metin dosyasının seçilen satırlarını boyut sınırıyla okur. |
| `search_files` | Workspace içindeki metinlerde büyük/küçük harf duyarsız arama yapar. |
| `file_exists` | Dosya veya klasör varlığını makine kaydıyla doğrular. |
| `make_directory` | Workspace içinde güvenli klasör ağacı oluşturur. |
| `write_file` | Dosyayı oluşturur veya içeriğini tamamen değiştirir. |
| `replace_in_file` | Tam eşleşen metni kontrollü sayıda değiştirir. |
| `run_terminal` | İzinli programı shell olmadan argüman listesiyle çalıştırır. |
| `git_status`, `git_diff` | Git çalışma ağacını salt okunur inceler. |
| `search_web` | İnternet açıksa Bing sonuçlarını başlık, URL ve özetle döndürür. |
| `fetch_url` | Güvenli bir genel HTTP(S) sayfasını metin olarak getirir. |
| `validate_web_assets` | HTML/CSS içindeki yerel asset referanslarının varlığını denetler. |

Araç sonuçları model metninden ayrı olarak `tool_trace` içine kaydedilir. Final ajanı
“dosya yazıldı” iddiasını yalnızca başarılı `write_file`/`replace_in_file` makine
kaydı varsa kullanabilir. Aynı araç ve aynı argümanların üçüncü kez tekrarı döngü
koruması tarafından engellenir.

### Terminal izin listesi

`run_terminal` yalnızca şu program ailelerini kabul eder:

```text
python, python3, pytest, git, ls, find, pwd, cat, head, tail,
node, npm, pnpm, yarn, ruff, mypy, cargo, go
```

- `python`, `python3` ve `node` yalnızca workspace içindeki bir betiği çalıştırabilir.
- `git` yalnızca `status`, `diff`, `log`, `show`, `branch`, `rev-parse` alt komutlarını
  kabul eder.
- Paket araçlarında test, lint, typecheck, check, build ve benzeri izinli alt komutlar
  kullanılabilir; kurulum/yayınlama komutları engellenir.
- Tek komut süresi `1–900` saniye arasında sınırlandırılır.
- `;`, `&&`, `||`, pipe, yönlendirme, backtick ve `$(` gibi shell operatörleri reddedilir.

- Shell çalıştırılmaz; komutlar argüman listesiyle başlatılır.
- Shell operatörleri ve workspace dışı yollar engellenir.
- Git aracı yalnızca salt-okunur alt komutları kabul eder.
- Python/Node yalnızca seçilen klasördeki betikleri çalıştırabilir.
- npm/pnpm/yarn/cargo/go yalnızca test, lint, check ve build sınıfı alt komutlarla sınırlıdır.
- Salt-okunur görevde `write_file` ve `replace_in_file` şemaları modelden tamamen kaldırılır.
- Nihai yanıt başarılı dosya değişikliklerini yalnızca makine araç izinden kabul eder.

Çalıştırılan proje kodunun kendisi kötü niyetli olabilir. Bu araç listesi bir sanal
makine veya işletim sistemi sandbox'ı değildir; güvenmediğiniz kodu çalıştırmayın.

## M1 Pro / 16 GB önerisi

Kurulum danışmanı bu donanımda standart `qwen3.5:9b` tabanını; çalışma ayarları
`context_size: 8192`, `think: false` ve `keep_alive: 5m` değerlerini önerir. Basit
görevlerde `balanced`/`fast`, gerçekten kapsamlı görevlerde `deep` kullanılmalıdır.
Bellek baskısında:

1. `context_size` değerini `4096` yapın.
2. `qwen3.5:4b` modeline geçin.
3. Hızlı veya Dengeli profili seçin.
4. Kullanılmayan modeli `ollama stop MODEL` ile boşaltın.

Uzman sayısını artırmak RAM'i esas olarak artırmaz, fakat toplam çalışma süresini ve
bağlam özetleme ihtiyacını artırır.

## Bilinen sınırlar ve sonraki geliştirmeler

- Yerel uzmanlar bu sürümde sıralı çalışır. `parallel`/`adaptive` worker havuzu ve
  izole worktree birleştirmesi yol haritasındadır; henüz etkin bir ayar değildir.
- Sonuç kalitesi seçilen yerel modelin araç çağırma, uzun bağlam ve talimat izleme
  becerisine bağlıdır. Küçük modeller eski ajan çıktısındaki bir bulguyu yeni araç
  kanıtına rağmen tekrarlayabilir. Nihai kararların zaman damgalı, yapılandırılmış
  kabul kriteri kayıtlarından hesaplanması planlanmaktadır.
- Token sayımı sağlayıcının/Ollama'nın bildirdiği sayaçtır; parasal maliyet tahmini
  yapılmaz.
- `search_web`, Bing HTML yapısına bağlı anahtarsız bir adaptördür; arama motoru
  biçimi değişirse sonuç ayrıştırıcı güncelleme gerektirebilir.
- Terminal test aracı tek başına tarayıcı görsel regresyonu veya gerçek cihaz
  emülasyonu sağlamaz.
  Böyle bir kabul kriteri için projede ayrıca Playwright/Cypress gibi bir test düzeni
  bulunmalıdır.
- Dosya ve terminal araçlarının sınırları güçlü korumalar sağlasa da MODAI işletim
  sistemi seviyesinde sanal makine/container sandbox'ı değildir.
- ChatGPT/Claude/Gemini web üyeliğiyle tarayıcı oturumu devralma yapılmaz; hibrit kip
  resmi API anahtarı gerektirir.

Planlanan en yüksek öncelikli geliştirmeler:

1. Her görev için dosya, test ve kabul ölçütlerinden oluşan makine tarafından
   doğrulanabilir artifact manifest.
2. Kalite ajanlarının serbest metin `PASS/FAIL` çıktısına ek olarak yapılandırılmış
   bulgu kimliği, kanıt zamanı ve çözüldü durumu üretmesi.
3. Uzun koşularda tam ajan metni yerine karar/kanıt özetleri kullanarak bağlam ve
   token tüketiminin azaltılması.
4. Güçlü makineler için bağımlılık DAG'ı, sınırlı paralel worker havuzu, dosya kilidi
   ve izole Git worktree birleştirmesi.
5. HTML görevleri için isteğe bağlı yerel browser smoke testi, erişilebilirlik ve
   responsive ekran görüntüsü doğrulaması.
6. Aynı kanıtın `list_files`, `ls` ve `file_exists` gibi farklı araçlarla gereksiz
   tekrarını tanıyan semantik araç önbelleği ve tur başına kanıt bütçesi.
7. Yerel-first raster görsel üretimi için ayrı sağlayıcı adaptörü, dosya metadata
   kaydı ve görev başına açık bulut izni.

## Testler

```bash
.venv/bin/python -m unittest discover -s tests -v
python3 -m compileall -q .
python3 -m json.tool config.json >/dev/null
zsh -n run.sh setup.sh install-command.sh
```

Mevcut paket 51 otomatik test içerir. Yapılandırma ve CLI sınırları, localhost
zorunluluğu, dinamik workspace, yol/shell güvenliği, native ve JSON araç döngüsü,
bozuk/çoklu araç çağrıları, tekrar koruması, gerçek dosya yazma zorunluluğu, token
bütçesi, kalite kapıları, eski koşu migrasyonu, salt-okunur mod, macOS CSI/SS3 ok
dizileri, prompt imleci/yapıştırma, iki dilli menü, klasör tarayıcı, rol kataloğu,
bağımlılık sıralaması, checkpoint/resume, donanım model önerisi, Modelfile üretimi,
yerel web asset doğrulaması, bulut yönlendirme ve web sonuç ayrıştırmasını kapsar.

Gerçek model duman testi otomatik testlerden ayrıdır; yerel Ollama modelinin araç
çağırma davranışını ölçerken token ve zaman tüketebilir. Yayın öncesinde geçici bir
workspace üzerinde en az `make_directory → write_file → read_file` akışı doğrulanır.

## Sorun giderme

### `modai: command not found`

```bash
cd /MODAI/KLASORU
./install-command.sh
export PATH="$HOME/.local/bin:$PATH"
```

PATH satırını `~/.zprofile` içine ekledikten sonra yeni terminal açın veya
`source ~/.zprofile` çalıştırın. Bağlantıyı `command -v modai` ile kontrol edin.

### Ollama bağlantısı veya model hatası

- Ollama uygulamasını açın ya da `ollama serve` çalıştırın.
- Bağlantıyı `ollama list` ile kontrol edin.
- Model bulunamazsa `ollama pull MODEL` kullanın veya proje modelini yeniden üretmek
  için `./setup.sh` çalıştırın.
- Yerel Ollama bağlantısı sistem/VPN HTTP proxy'sini otomatik atlar.

### Ok tuşunda menü kapanıyor veya terminal bozuluyor

- Eski çalışan MODAI süreçlerinin yeni terminal girdisini paylaşmadığını kontrol edin.
- Yeni sürümü tekrar başlatın; CSI ve SS3 ok dizilerinin ikisi de desteklenir.
- Satırlar sağa kayıyor, üst üste biniyor veya giriş görünmüyorsa MODAI kapandıktan
  sonra bir kez `stty sane` çalıştırın.
- Renkler okunmuyorsa `modai --no-color` veya `NO_COLOR=1 modai` kullanın.
- Terminali en az 60 sütun genişletmek büyük logoyu gösterir; daha dar görünümde
  kompakt başlık bilinçli olarak kullanılır.

### Görev çok fazla token kullanıyor

- `/status` ve canlı telemetride toplamı izleyin.
- Daha küçük `context_size`, `fast`/`balanced` profil ve daha net görev kapsamı kullanın.
- `max_tool_rounds` ve `agent_retries` değerlerini artırmak yerine önce tekrarlanan
  aracın neden başarısız olduğunu inceleyin.
- Bütçe dolarsa görev kaybolmaz; daha yüksek `--max-total-tokens` ile devam ettirilebilir.
- Eski ve çok şişmiş bir koşuyu sürdürmek yerine mevcut dosyalardan yeni, odaklı bir
  görev başlatmak çoğu zaman daha verimlidir.

### Kalite kapısı geçmiyor

`modai --list-runs` ile durumu görün. `needs_attention` koşuda eksik ajan kapasitesi
varsa hem `--repair-rounds` hem `--max-agents` artırılmalıdır. Kabul kriteri belirsiz
veya dış bağımlılık eksikse promptu netleştirerek yeni görev başlatın. MODAI `FAIL`
kapısını gizleyerek görevi tamamlandı saymaz.

### Bulut sağlayıcısı çalışmıyor

- `/cloud` ile sağlayıcı, model ve durum değerlerini kontrol edin.
- `/cloud setup` ile API anahtarını yeniden kaydedin veya ilgili ortam değişkenini
  (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`) ayarlayın.
- ChatGPT, Claude veya Gemini web aboneliği API erişimi yerine geçmez; sağlayıcının
  API anahtarı ve API kotası gerekir.
- Bulut hatasında uygun iş paketi yerel modele döner; gizli görevlerde `/cloud off`
  kullanın.

### Python/venv kurulumu başarısız

Homebrew `pyexpat` veya pip sembol hatasında:

```bash
brew install python@3.13
MOD_AGENT_PYTHON=python3.13 ./setup.sh
```

### Ajanın terminal komutu engellendi

Bu çoğunlukla güvenlik politikasının beklenen sonucudur. Shell zinciri, paket kurma,
mutating Git komutu veya workspace dışı yol yerine izinli, tek bir test/build komutu
kullanın. Güvenlik sınırını aşmak için ajan promptuna talimat vermek izinleri değiştirmez.
