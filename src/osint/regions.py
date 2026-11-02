# ruff: noqa: E501  (the term table holds wide CJK/Arabic text; wrapping it would hide the terms)
"""Tag a report with the regions it is about, from place names, organisations and leaders.

Rule-based and multilingual: each region lists terms in the languages we collect. It is meant for
filtering, so it errs toward tagging every region a report plainly mentions; one report can carry
several (a story about Chinese ships near the Philippines is both South China Sea and China).

Term syntax (matching ignores case):
  ``=word``    the whole word only (``=india`` does not match "Indiana")
  ``^WORD``    the whole word, upper case only (``^US`` does not match the pronoun "us")
  ``stem``     any word that starts with it (``korea`` matches "Koreans"); this is how inflected
               Russian, Turkish or Vietnamese forms are caught
  CJK/Thai     substring, since those scripts have no spaces
"""

import re
from dataclasses import dataclass

CJK = re.compile(r"[฀-๿぀-ヿ㐀-鿿가-힯]")


def _compile(terms: list[str]) -> re.Pattern:
    parts = []
    for term in terms:
        if term.startswith("="):
            parts.append(r"(?<!\w)" + re.escape(term[1:]) + r"(?!\w)")
        elif term.startswith("^"):
            parts.append(r"(?-i:(?<!\w)" + re.escape(term[1:]) + r"(?!\w))")
        elif CJK.search(term):
            parts.append(re.escape(term))
        else:
            parts.append(r"(?<!\w)" + re.escape(term))
    return re.compile("|".join(parts), re.IGNORECASE)


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    pattern: re.Pattern


def _r(region_id: str, name: str, *terms: str) -> Region:
    return Region(region_id, name, _compile(list(terms)))


# fmt: off
REGIONS: list[Region] = [
    _r('bien_dong', 'Biển Đông',
       'south china sea', 'west philippine sea', '=spratly', '=spratlys', '=paracel', '=paracels',
       'scarborough', 'second thomas', 'sabina shoal', 'reed bank', 'nine-dash', 'biển đông',
       'trường sa', 'hoàng sa', 'южно-китайск', '南海', '南沙', '西沙', '黄岩岛', '仁爱礁',
       '남중국해', '南シナ海', 'بحر الصين الجنوبي'),
    _r('dong_nam_a', 'Đông Nam Á',
       '=vietnam', '=vietnamese', 'philippin', '=filipino', '=malaysia', '=malaysian',
       '=indonesia', '=indonesian', '=thailand', '=singapore', '=myanmar', '=burma', '=cambodia',
       '=laos', '=brunei', 'timor', '=asean', '=manila', '=hanoi', '=jakarta', '=bangkok',
       'kuala lumpur', '=marcos', 'việt nam', 'thái lan', 'campuchia', 'đông nam á', 'hà nội',
       'вьетнам', 'филиппин', 'малайзи', 'индонези', 'таиланд', 'сингапур', 'мьянм', 'камбодж',
       'асеан', '越南', '菲律宾', '菲律賓', '马来西亚', '印尼', '印度尼西亚', '泰国', '新加坡',
       '缅甸', '柬埔寨', '东盟', '东南亚', '베트남', '필리핀', '말레이시아', '인도네시아', '태국',
       '싱가포르', '미얀마', '동남아', 'ベトナム', 'フィリピン', 'マレーシア', 'インドネシア',
       'シンガポール', 'ミャンマー', '東南アジア', 'الفلبين', 'فيتنام', 'إندونيسيا', 'ماليزيا',
       'سنغافورة'),
    _r('dong_bac_a', 'Đông Bắc Á',
       'northeast asia', 'north east asia', '=japan', '=japanese', '=tokyo', 'korea',
       '=pyongyang', '=seoul', '=taiwan', '=taiwanese', '=taipei', '=mongolia', '=okinawa',
       '=senkaku', '=kuril', '=kurils', 'sea of japan', 'yellow sea', 'đông bắc á', 'nhật bản',
       'triều tiên', 'hàn quốc', 'bình nhưỡng', 'đài loan', 'япони', 'корей', 'кндр', 'тайван',
       'токио', 'сеул', 'пхеньян', 'курил', 'монголи', '日本', '朝鲜', '朝鮮', '韩国', '韓國',
       '台湾', '台灣', '东京', '東京', '首尔', '首爾', '平壤', '蒙古', '东北亚', '일본', '북한',
       '한국', '대만', '도쿄', '서울', '평양', '동북아', '北朝鮮', '韓国', 'ソウル', '平壌',
       '東北アジア', 'اليابان', 'كوريا', 'تايوان'),
    _r('trung_quoc', 'Trung Quốc',
       '=china', '=chinese', '=beijing', '=prc', '^PLA', '^PLAN', 'xi jinping', '^CCP',
       'hong kong', '=shanghai', '=shenzhen', '=zhuhai', 'liberation army', '=huawei', '=comac',
       '=norinco', 'trung quốc', 'bắc kinh', 'tập cận bình', 'кита', 'пекин', '中国', '中國',
       '北京', '解放军', '解放軍', '习近平', '習近平', '中共', '香港', '중국', '베이징', '시진핑',
       '인민해방군', '中国', '習近平', '人民解放軍', 'الصين', 'بكين', 'چین', 'çin', 'chine',
       'chinois', 'chinesisch', '我国', '我军', '中央军委', '军委', '集团军', '陆航', '国防大学'),
    _r('dai_loan', 'Đài Loan',
       '=taiwan', '=taiwanese', '=taipei', '=kmt', 'lai ching-te', '=penghu', '=kinmen', '=matsu',
       'đài loan', 'тайван', '台湾', '台灣', '台海', '臺灣', '两岸', '兩岸', '대만', '타이완',
       'تايوان'),
    _r('trieu_tien', 'Triều Tiên',
       'north korea', '=pyongyang', 'kim jong', '=dprk', '=kcna', 'triều tiên', 'bình nhưỡng',
       'кндр', 'пхеньян', 'ким чен', '朝鲜', '朝鮮', '平壤', '金正恩', '북한', '평양', '김정은',
       '조선인민군', '北朝鮮', '平壌', 'كوريا الشمالية', 'corée du nord', 'nordkorea',
       'corea del norte', '朝方'),
    _r('han_quoc', 'Hàn Quốc',
       'south korea', '=seoul', 'republic of korea', '^ROK', '=yonhap', 'lee jae-myung',
       '=hanwha', 'hàn quốc', 'южной коре', 'южная коре', 'сеул', '韩国', '韓國', '首尔', '首爾',
       '한국', '서울', '대한민국', '이재명', '韓国', 'ソウル', 'كوريا الجنوبية', 'corée du sud',
       'südkorea', 'corea del sur', '韩军', '韩方', '中韩'),
    _r('nhat_ban', 'Nhật Bản',
       '=japan', '=japanese', '=tokyo', '=jsdf', '=okinawa', '=senkaku', 'nhật bản', 'япони',
       'токио', '日本', '东京', '東京', '自卫队', '自衛隊', '일본', '도쿄', '防衛省', 'اليابان',
       'japon', 'japón', '日方', '日军', '中日'),
    _r('nga', 'Nga',
       '=russia', '=russian', '=moscow', '=kremlin', '=putin', 'rosj', 'rosyj', '=lavrov', '=belousov', '=shoigu',
       '=gerasimov', '=wagner', '=nga', 'putin', 'росси', '=рф', 'москв', 'кремл', 'путин',
       '俄罗斯', '俄羅斯', '莫斯科', '普京', '克里姆林', '러시아', '모스크바', '푸틴', '크렘린',
       'ロシア', 'モスクワ', 'プーチン', 'روسيا', 'موسكو', 'بوتين', 'rusya', 'russie', 'moscou',
       'poutine', 'russland', 'moskau', 'rusia', 'moscú', '俄国', '俄方', '俄军', '俄乌', '中俄'),
    _r('ukraine', 'Ukraine',
       '=ukraine', '=ukrainian', '=kyiv', '=kiev', 'zelensk', '=donbas', '=donbass', '=kherson',
       '=kharkiv', '=kharkov', 'zaporizh', '=zaporozhye', '=odesa', '=odessa', '=crimea',
       '=bakhmut', '=oleshky', '=avdiivka', 'украин', 'киев', 'зеленск', 'донбасс', 'херсон',
       'харьков', 'запорожь', 'одесс', 'крым', '=сво', 'україн', 'київ', 'зеленськ', 'харків',
       'запоріж', 'одес', 'крим', 'зсу', '乌克兰', '烏克蘭', '基辅', '泽连斯基', '澤連斯基',
       '顿巴斯', '克里米亚', '우크라이나', '키이우', '젤렌스키', 'ウクライナ', 'キーウ',
       'ゼレンスキー', 'أوكرانيا', 'كييف', 'زيلينسكي', 'ukrayna', 'kiew', 'ucrania', '俄乌'),
    _r('chau_au', 'Châu Âu, NATO',
       '=nato', '=europe', '=european', '=eu', '=brussels', '=germany', '=german', '=france',
       '=french', '=britain', '=british', '^UK', '=london', '=poland', '=polish', '=baltic',
       '=finland', '=sweden', '=norway', '=denmark', '=netherlands', '=dutch', '=italy', '=spain',
       '=romania', '=bulgaria', '=greece', '=bundeswehr', 'polsk', 'białorus', 'châu âu', 'liên minh châu âu',
       'ba lan', 'phần lan', 'thụy điển', 'na uy', 'đan mạch', 'hà lan', 'tây ban nha', 'hy lạp',
       'европ', 'нато', '=ес', 'германи', 'франци', 'британи', 'великобритани', 'польш',
       'финлянд', 'швеци', 'норвег', 'нидерланд', 'итали', 'испани', 'румын', 'болгари', '欧洲',
       '歐洲', '北约', '北約', '欧盟', '歐盟', '德国', '德國', '法国', '法國', '英国', '英國',
       '波兰', '波蘭', '芬兰', '瑞典', '挪威', '丹麦', '荷兰', '意大利', '西班牙', '罗马尼亚',
       '保加利亚', '希腊', '유럽', '나토', '독일', '프랑스', '영국', '폴란드', '핀란드', '스웨덴',
       '노르웨이', '欧州', 'ドイツ', 'フランス', 'イギリス', 'ポーランド', 'フィンランド',
       'أوروبا', 'الناتو', 'ألمانيا', 'فرنسا', 'بريطانيا', 'europe', 'otan', 'allemagne',
       'royaume-uni', 'europa', 'deutschland', '=latvia', '=lithuania', '=estonia', '=belarus', '=belarusian', '=minsk', '=switzerland', '=swiss', '=austria', '=czech', '=slovakia', '=hungary', '=serbia', '=kosovo', '=moldova', '=ireland', '=portugal', '=belgium', '=croatia', '=slovenia', '=albania', '=berlin', '=paris', '=rome', '=madrid', '=warsaw', '=prague', '=vienna', '=budapest', '=stockholm', '=oslo', '=helsinki', '=copenhagen', '=hannover', '=hanover', '=hamburg', '=munich', 'латви', 'литв', 'эстони', 'беларус', 'белорус', 'швейцари', 'чех', 'словаки', 'венгри', 'серби', 'молдов', '拉脱维亚', '立陶宛', '爱沙尼亚', '白俄罗斯', '瑞士', '捷克', '匈牙利', '塞尔维亚', 'latvia', 'litva', 'estonia'),
    _r('trung_dong', 'Trung Đông',
       'middle east', 'persian gulf', '=gulf', 'hormuz', '=syria', '=syrian', '=iraq', '=iraqi',
       '=yemen', '=yemeni', 'houthi', '=saudi', '=uae', '=emirates', '=qatar', '=kuwait',
       '=bahrain', '=oman', '=lebanon', '=lebanese', '=hezbollah', '=turkey', '=turkish',
       'türkiye', '=ankara', '=erbil', '=kurdish', '=kurds', 'red sea', '=gaza', 'west bank',
       '=israel', '=israeli', '=hamas', '=tehran', '=iran', '=iranian', 'trung đông',
       'vịnh ba tư', 'ả rập', 'liban', 'thổ nhĩ kỳ', 'dải gaza', 'ближн восток', 'ближнем восток',
       'ближнего восток', 'сири', 'ирак', 'йемен', 'хуси', 'саудовск', 'катар', 'кувейт', 'ливан',
       'хезболл', 'турци', 'сектор газа', 'сектора газа', 'израил', 'хамас', 'иран', 'тегеран',
       '中东', '中東', '伊朗', '以色列', '加沙', '叙利亚', '敘利亞', '伊拉克', '也门', '胡塞',
       '沙特', '卡塔尔', '黎巴嫩', '真主党', '土耳其', '霍尔木兹', '霍爾木茲', '德黑兰', '중동',
       '이란', '이스라엘', '가자', '시리아', '이라크', '예멘', '후티', '사우디', '카타르',
       '레바논', '헤즈볼라', '튀르키예', '호르무즈', '테헤란', 'イラン', 'イスラエル', 'ガザ',
       'シリア', 'イラク', 'イエメン', 'フーシ', 'サウジ', 'カタール', 'レバノン', 'ヒズボラ',
       'トルコ', 'ホルムズ', 'テヘラン', 'الشرق الأوسط', 'إيران', 'إسرائيل', 'غزة', 'سوريا',
       'العراق', 'اليمن', 'الحوثي', 'السعودية', 'قطر', 'الكويت', 'لبنان', 'حزب الله', 'تركيا',
       'هرمز', 'طهران', 'فلسطين', 'حماس', 'الخليج', 'ایران', 'اسرائیل', 'تهران', 'غزه', 'سوریه',
       'عراق', 'یمن', 'حوثی', 'عربستان', 'ترکیه', 'هرمز', 'orta doğu', 'israil', 'gazze',
       'suriye', 'irak', 'husi', 'suudi', 'katar', 'lübnan', 'hizbullah', 'hürmüz', 'tahran',
       'moyen-orient', 'israël', 'syrie', 'yémen', 'houthis', 'turquie', 'ormuz', 'téhéran',
       'naher osten', 'syrien', 'jemen', 'huthi', 'libanon', 'hisbollah', 'türkei', 'hormus',
       'teheran', 'oriente medio', 'irán', 'siria', 'hutíes', 'líbano', 'hizbulá', 'turquía',
       'teherán'),
    _r('iran', 'Iran',
       '=iran', '=iranian', '=iranians', '=tehran', '=irgc', '=khamenei', 'иран', 'тегеран',
       '伊朗', '德黑兰', '革命卫队', '이란', '테헤란', 'イラン', 'テヘラン', 'إيران', 'طهران',
       'ایران', 'تهران', 'tahran', 'irán', 'téhéran', 'teheran', 'teherán'),
    _r('israel_gaza', 'Israel, Gaza',
       '=israel', '=israeli', '=gaza', '=hamas', '=idf', '=netanyahu', 'west bank', 'dải gaza',
       'израил', 'сектор газа', 'сектора газа', 'хамас', 'нетаньяху', '以色列', '加沙', '哈马斯',
       '内塔尼亚胡', '이스라엘', '가자', '하마스', '네타냐후', 'イスラエル', 'ガザ', 'ハマス',
       'ネタニヤフ', 'إسرائيل', 'غزة', 'حماس', 'نتنياهو', 'اسرائیل', 'غزه', 'israil', 'gazze',
       'israël', 'hamás'),
    _r('my', 'Mỹ',
       '^US', '^U.S.', '^USA', 'united states', '=american', '=americans', '=america',
       '=pentagon', '=washington', 'white house', '=hegseth', '=trump', '=rubio', '=cia', '=fbi',
       '=nsa', '=congress', '=usmc', '=darpa', '=centcom', '=socom', 'department of war', 'mỹ',
       'hoa kỳ', 'lầu năm góc', 'nhà trắng', 'сша', 'америк', 'пентагон', 'вашингтон', 'трамп',
       'белый дом', '美国', '美國', '五角大楼', '五角大樓', '白宫', '白宮', '华盛顿', '特朗普',
       '川普', '미국', '펜타곤', '백악관', '워싱턴', '트럼프', '米国', 'アメリカ', '国防総省',
       'ペンタゴン', 'ホワイトハウス', 'トランプ', 'الولايات المتحدة', 'أمريكا', 'البنتاغون',
       'واشنطن', 'ترامب', 'آمریکا', 'ایالات متحده', 'ترامپ', 'واشنگتن', '=abd', 'amerika',
       'états-unis', 'pentagone', 'vereinigte staaten', 'estados unidos', 'pentágono', 'अमेरिका',
       '美方', '美军', '中美'),
    _r('nam_a', 'Nam Á',
       '=india', '=indian', '=delhi', '=modi', '=pakistan', '=pakistani', '=islamabad',
       '=kashmir', '=afghanistan', '=afghan', '=taliban', '=kabul', '=bangladesh', '=dhaka',
       'sri lanka', '=nepal', '=bhutan', '=maldives', '=drdo', '=isro', '=iaf', 'ấn độ', 'кашмир', 'пакистан',
       'афганистан', 'талибан', 'бангладеш', 'шри-ланк', 'непал', '=индия', '=индии', '=индию',
       'индийск', 'нью-дели', '印度', '巴基斯坦', '克什米尔', '阿富汗', '塔利班', '孟加拉',
       '斯里兰卡', '尼泊尔', '인도', '파키스탄', '카슈미르', '아프가니스탄', '탈레반',
       '방글라데시', 'インド', 'パキスタン', 'カシミール', 'アフガニスタン', 'タリバン', 'الهند',
       'باكستان', 'كشمير', 'أفغانستان', 'طالبان', 'भारत', 'पाकिस्तान', 'hindistan', 'afganistan',
       'keşmir', 'inde', 'cachemire', 'indien', 'kaschmir', 'pakistán', 'cachemira', 'afganistán',
       '印方', '印军', '中印'),
    _r('chau_phi', 'Châu Phi',
       '=africa', '=african', '=sudan', '=sudanese', '=ethiopia', '=ethiopian', '=libya',
       '=libyan', '=mali', '=sahel', '=somalia', '=nigeria', '=niger', '=congo', '=egypt',
       '=egyptian', '=kenya', '=uganda', '=mozambique', '=tunisia', '=algeria', '=morocco',
       'burkina', '=cameroon', '^RSF', '=tigray', 'châu phi', 'ai cập', 'африк', 'судан',
       'эфиопи', 'ливи', 'сахел', 'сомали', 'нигери', 'египет', 'конго', '非洲', '苏丹',
       '埃塞俄比亚', '利比亚', '马里', '萨赫勒', '索马里', '尼日利亚', '埃及', '刚果', '아프리카',
       '수단', '에티오피아', '리비아', '말리', '사헬', '소말리아', '나이지리아', '이집트', '콩고',
       'アフリカ', 'スーダン', 'エチオピア', 'リビア', 'マリ', 'サヘル', 'ソマリア',
       'ナイジェリア', 'エジプト', 'コンゴ', 'أفريقيا', 'السودان', 'إثيوبيا', 'ليبيا', 'مالي',
       'الصومال', 'نيجيريا', 'مصر', 'الكونغو', 'afrique', 'soudan', 'éthiopie', 'libye',
       'somalie', 'égypte', 'afrika', 'äthiopien', 'libyen', 'ägypten', 'kongo', 'áfrica',
       'sudán', 'etiopía', 'libia', 'malí', 'egipto', 'etiyopya', 'mısır'),
    _r('bac_cuc', 'Bắc Cực',
       '=arctic', '=greenland', 'high north', '=svalbard', '=nuuk', 'north pole',
       'northern sea route', '=aleutian', '=aleutians', 'bắc cực', 'арктик', 'гренланд',
       'шпицберген', '北极', '北極', '格陵兰', '格陵蘭', '북극', '그린란드', 'グリーンランド',
       'القطب الشمالي', 'غرينلاند', 'arctique', 'groenland', 'arktis', 'grönland', 'ártico',
       'groenlandia'),
    _r('chau_uc_tbd', 'Úc, Thái Bình Dương',
       '=australia', '=australian', '=canberra', '=aukus', 'new zealand', 'pacific', '=guam',
       '=palau', '=fiji', 'solomon islands', 'papua new guinea', '=vanuatu', '=tonga',
       '=micronesia', 'indo-pacific', '=indopacom', '=pacom', '=pacfleet', 'thái bình dương',
       '=úc', 'австрали', 'аукус', 'новая зеландия', 'тихом океан', 'тихоокеан', '澳大利亚',
       '澳洲', '奥库斯', '新西兰', '太平洋', '关岛', '印太', '호주', '오커스', '뉴질랜드',
       '태평양', '괌', '인도태평양', 'オーストラリア', '豪州', 'オーカス', 'ニュージーランド',
       '太平洋', 'グアム', 'インド太平洋', 'أستراليا', 'أوكوس', 'المحيط الهادئ', 'australie',
       'nouvelle-zélande', 'pacifique', 'australien', 'neuseeland', 'pazifik', 'nueva zelanda',
       'pacífico'),
    _r('my_latinh', 'Mỹ Latinh',
       'latin america', '=venezuela', '=venezuelan', '=maduro', '=brazil', '=brazilian', '=lula',
       '=cuba', '=cuban', '=mexico', '=mexican', '=colombia', '=colombian', '=argentina',
       '=chile', '=peru', '=ecuador', '=panama', '=caribbean', '=haiti', '=nicaragua',
       '=honduras', '=guatemala', '=caracas', '=bolivia', '=guyana', '=cartel', '=cartels',
       'mỹ latinh', 'venezuela', 'brazil', 'mexico', 'colombia', 'argentina', 'maduro', 'латинск',
       'венесуэл', 'бразили', 'кубинск', 'мексик', 'колумби', 'аргентин', 'мадуро', '拉美',
       '拉丁美洲', '委内瑞拉', '巴西', '古巴', '墨西哥', '哥伦比亚', '阿根廷', '马杜罗', '卢拉',
       '중남미', '베네수엘라', '브라질', '쿠바', '멕시코', '콜롬비아', '아르헨티나', '마두로',
       '룰라', '中南米', 'ベネズエラ', 'ブラジル', 'キューバ', 'メキシコ', 'コロンビア',
       'アルゼンチン', 'マドゥロ', 'ルラ', 'أمريكا اللاتينية', 'فنزويلا', 'البرازيل', 'كوبا',
       'المكسيك', 'كولومبيا', 'مادورو', 'amérique latine', 'brésil', 'mexique', 'colombie',
       'lateinamerika', 'brasilien', 'kuba', 'mexiko', 'kolumbien', 'latinoamérica',
       'américa latina', 'brasil', 'méxico', 'brezilya', 'küba', 'meksika', 'kolombiya'),
]
# fmt: on

# The order chips are shown in: the regions this desk watches most closely first.
DISPLAY_ORDER = [
    "bien_dong",
    "dong_nam_a",
    "dong_bac_a",
    "trung_quoc",
    "han_quoc",
    "nga",
    "ukraine",
    "trung_dong",
    "iran",
    "my",
    "dai_loan",
    "trieu_tien",
    "nhat_ban",
    "chau_au",
    "israel_gaza",
    "nam_a",
    "chau_phi",
    "bac_cuc",
    "chau_uc_tbd",
    "my_latinh",
]
_BY_ID = {r.id: r for r in REGIONS}
assert set(DISPLAY_ORDER) == set(_BY_ID), "every region needs a display position"


def region_name(region_id: str) -> str:
    return _BY_ID[region_id].name


BODY_MENTIONS = 2


def tag(title: str | None, body: str | None = None) -> list[str]:
    """Region ids a report is about, in display order.

    A region named in the headline counts. One named only in the body must come up at least twice,
    so a passing mention (a list of countries, a dateline) does not tag the whole story.
    """
    title = title or ""
    body = body or ""
    found = []
    for rid in DISPLAY_ORDER:
        pattern = _BY_ID[rid].pattern
        if pattern.search(title) or len(pattern.findall(body)) >= BODY_MENTIONS:
            found.append(rid)
    return found


# A report that names no place is, for a national outlet, about that outlet's own country: a US
# trade paper's story on the Army's reorganisation is a US story whether or not it says so. Applied
# only when nothing else tagged the report. Keys are the outlet's site, without "www.".
HOME_REGION = {
    "militarytimes.com": "my",
    "defensenews.com": "my",
    "breakingdefense.com": "my",
    "defenseone.com": "my",
    "news.usni.org": "my",
    "defense.gov": "my",
    "war.gov": "my",
    "twz.com": "my",
    "thedrive.com": "my",
    "c4isrnet.com": "my",
    "defensescoop.com": "my",
    "airandspaceforces.com": "my",
    "taskandpurpose.com": "my",
    "dvidshub.net": "my",
    "af.mil": "my",
    "spaceforce.mil": "my",
    "nextgov.com": "my",
    "federalnewsnetwork.com": "my",
    "tass.com": "nga",
    "tass.ru": "nga",
    "ria.ru": "nga",
    "lenta.ru": "nga",
    "rg.ru": "nga",
    "kommersant.ru": "nga",
    "interfax.ru": "nga",
    "tvzvezda.ru": "nga",
    "themoscowtimes.com": "nga",
    "xinhuanet.com": "trung_quoc",
    "globaltimes.cn": "trung_quoc",
    "yna.co.kr": "han_quoc",
    "en.yna.co.kr": "han_quoc",
    "chosun.com": "han_quoc",
    "koreaherald.com": "han_quoc",
    "koreatimes.co.kr": "han_quoc",
    "japantimes.co.jp": "nhat_ban",
    "asahi.com": "nhat_ban",
    "mainichi.jp": "nhat_ban",
    "taipeitimes.com": "dai_loan",
    "pravda.com.ua": "ukraine",
    "ukrinform.net": "ukraine",
    "ukrinform.ua": "ukraine",
    "kyivindependent.com": "ukraine",
    "armyinform.com.ua": "ukraine",
    "defence24.pl": "chau_au",
    "rp.pl": "chau_au",
    "hartpunkt.de": "chau_au",
    "esut.de": "chau_au",
    "opex360.com": "chau_au",
    "euro-sd.com": "chau_au",
    "indiandefencereview.com": "nam_a",
    "idrw.org": "nam_a",
    "pib.gov.in": "nam_a",
    "savunmasanayist.com": "trung_dong",
    "aa.com.tr": "trung_dong",
    "trthaber.com": "trung_dong",
}


def tag_report(title: str | None, body: str | None = None, site: str | None = None) -> list[str]:
    """``tag`` plus the outlet's home region when the report names no place at all."""
    found = tag(title, body)
    if not found and site:
        home = HOME_REGION.get(site.removeprefix("www."))
        if home:
            return [home]
    return found
