# MODAI 3.1

> **Depo durumu:** Bu ilk yayın yalnızca proje tanımı ve teknik yol haritasıdır.
> Kaynak kod, yerel macOS/M1 doğrulaması ve kullanıcı onayından sonra ayrıca
> yayımlanacaktır.

M1 Pro / 16 GB için tasarlanmış, **tek bir yerel Ollama modeli** kullanan uzman-ajan
orkestratörü. Ajan sayısı model kopyası sayısı değildir: bütün uzmanlar aynı modeli
sırayla kullanır. Böylece bir “ajan ordusu” görev üzerinde farklı bakış açılarıyla
çalışırken bellekte yalnızca tek model tutulur.

Model girdileri ve proje dosyaları yerel makinede kalır. İnternet araştırması açıksa
yalnızca arama sorguları ve ajanların açtığı web adresleri dış ağa gönderilir. Tamamen
çevrimdışı çalışmak için ana ekrandan interneti kapatın veya `--no-internet` kullanın.

## Hızlı başlangıç

Ollama uygulamasını açın, sonra:

```bash
cd /Users/bg/Desktop/mod-agent
./setup.sh
./run.sh
```

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
    Türkçe / English
    Çıkış
```

`↑`/`↓` ile gezin, `Enter` veya `→` ile açın, `q`, `Esc` veya `←` ile geri dönün.
Klasör seçici de yalnızca ok tuşlarıyla dizinler arasında gezebilir.

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

Varsayılan üst sınır 24 mantıksal ajan oturumudur; ayarlanabilir teknik sınır 48'dir.
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

Komut satırından:

```bash
./run.sh --profile deep --workspace /tam/proje/yolu "Ürünü incele, geliştir ve test et"
./run.sh --profile marathon --max-hours 24 "Girişim planını araştır ve doğrula"
```

`max_hours` yalnızca aktif model/ajan çalışma süresini sayar. Yapılandırmadaki üst
sınır 72 saattir.

## Uzun görevler ve devam ettirme

Her plan, ajan, araç çağrısı, tartışma ve kalite kapısından sonra atomik checkpoint
`memory/runs/<koşu-id>/state.json` dosyasına yazılır. `Ctrl+C`, süre sınırı veya hata
sonrasında görev kaldığı adımdan devam ettirilebilir:

```bash
./run.sh --list-runs
./run.sh --resume
./run.sh --resume 20260913-221012-991745
```

Ok tuşlu ana ekrandaki **Göreve devam et** seçeneği de duraklatılmış koşuları listeler.

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

## Model değiştirme

Model mimariden bağımsızdır. Yerel modelleri görmek ve değiştirmek için:

```bash
./run.sh --list-models
./run.sh --model gemma3:4b
MOD_AGENT_MODEL=gemma3:4b ./run.sh
```

Kalıcı varsayılan yalnızca [`config.json`](config.json) içindeki `model` satırıdır.
Model daha önce Ollama'ya indirilmiş olmalıdır:

```bash
ollama pull gemma3:4b
```

Gizlilik için `host` yalnızca `localhost`, `127.0.0.1` veya `::1` olabilir. Uzak model
sunucuları yapılandırma doğrulamasında reddedilir.

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

```text
/help
/menu
/agents
/models
/model MODEL
/workspace PATH
/internet on|off
/profile fast|balanced|deep|marathon
/language tr|en
/runs
/resume [KOŞU_ID]
/status
/clear
/exit
```

## Güvenlik sınırları

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

Varsayılan `context_size: 8192`, `think: false`, `keep_alive: 5m` ve Derin profile
yakın 24 ajan bütçesi kullanır. Bellek baskısında:

1. `context_size` değerini `4096` yapın.
2. 4B–7B kuantize bir modele geçin.
3. Hızlı veya Dengeli profili seçin.
4. Kullanılmayan modeli `ollama stop MODEL` ile boşaltın.

Uzman sayısını artırmak RAM'i esas olarak artırmaz, fakat toplam çalışma süresini ve
bağlam özetleme ihtiyacını artırır.

## Testler

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Test paketi yapılandırma, localhost zorunluluğu, dinamik workspace, yol/shell güvenliği,
native araç döngüsü, salt-okunur mod, macOS CSI/SS3 ok dizileri, iki dilli menü,
klasör tarayıcı, ajan kataloğu, bağımlılık sıralaması, checkpoint/resume ve web sonucu
ayrıştırmasını kapsar.

## Sorun giderme

- Ollama bağlantısı yoksa uygulamayı açın veya `ollama serve` çalıştırın.
- Model bulunamazsa `ollama pull MODEL` kullanın.
- Satırlar sağa kayıyor veya üst üste biniyorsa eski çalışan MODAI sürecini kapatıp
  yeni sürümü yeniden başlatın. Gerekirse bir kez `stty sane` çalıştırarak önceki
  sürecin bıraktığı terminal kipini sıfırlayın.
- Homebrew `pyexpat`/pip sembol hatasında `MOD_AGENT_PYTHON=python3.13 ./setup.sh` çalıştırın.
- Yerel Ollama bağlantısı sistem/VPN HTTP proxy'sini otomatik atlar.
