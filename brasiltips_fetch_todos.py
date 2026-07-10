"""
BrasilTips - Data Fetcher MULTI-CAMPEONATO (API-Football)
=========================================================
Puxa os 9 campeonatos da SEMANA INTEIRA (segunda a domingo) de uma vez e
gera UM arquivo pronto (campeonatos_prontos.json) que o app serve para
TODOS os usuários — sem consulta por usuário.

Roda 1x por dia (ou a cada 6h) num servidor. 10 mil ou 100 mil usuários
leem o mesmo arquivo. A API-Football é consultada poucas dezenas de vezes/dia.

Campeonatos (mesmos IDs que a v2.5 usa):
  brasil-a, brasil-b, ing-a, ing-b, esp-a, esp-b, fra-a, fra-b, ucl

COMO USAR:
    export APISPORTS_KEY="sua_chave_aqui"
    python brasiltips_fetch_todos.py
  → gera: campeonatos_prontos.json
"""

import os
import time
import json
import math
import datetime as dt

import requests

# ----------------------------------------------------------------------
# CONFIGURAÇÃO
# ----------------------------------------------------------------------
API_KEY = os.environ.get("APISPORTS_KEY", "COLE_SUA_CHAVE_AQUI")
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

ANO = dt.date.today().year
TEMPORADAS_3_ANOS = [ANO, ANO - 1, ANO - 2]
PAUSA = 0.4  # segundos entre chamadas (respeita o limite do plano)

# IDs da API-Football para cada campeonato (id_app -> dados da liga)
# league = id da liga na API-Football | promo = liga de onde "subiu" | rebaix = liga de onde "desceu"
LIGAS = {
    "brasil-a": {"nome": "Brasileirão Série A", "pais": "Brasil",     "flag": "🇧🇷", "divisao": "Série A",         "league": 71,  "rebaix": None, "promo": 72},
    "brasil-b": {"nome": "Brasileirão Série B", "pais": "Brasil",     "flag": "🇧🇷", "divisao": "Série B",         "league": 72,  "rebaix": 71,   "promo": 75},
    "ing-a":    {"nome": "Premier League",      "pais": "Inglaterra", "flag": "🏴", "divisao": "Premier League",  "league": 39,  "rebaix": None, "promo": 40},
    "ing-b":    {"nome": "EFL Championship",    "pais": "Inglaterra", "flag": "🏴", "divisao": "Championship",    "league": 40,  "rebaix": 39,   "promo": 41},
    "esp-a":    {"nome": "La Liga",             "pais": "Espanha",    "flag": "🇪🇸", "divisao": "La Liga",         "league": 140, "rebaix": None, "promo": 141},
    "esp-b":    {"nome": "La Liga Hypermotion", "pais": "Espanha",    "flag": "🇪🇸", "divisao": "La Liga 2",       "league": 141, "rebaix": 140,  "promo": 142},
    "fra-a":    {"nome": "Ligue 1",             "pais": "França",     "flag": "🇫🇷", "divisao": "Ligue 1",         "league": 61,  "rebaix": None, "promo": 62},
    "fra-b":    {"nome": "Ligue 2",             "pais": "França",     "flag": "🇫🇷", "divisao": "Ligue 2",         "league": 62,  "rebaix": 61,   "promo": 63},
    "ucl":      {"nome": "UEFA Champions League","pais": "Champions", "flag": "🏆", "divisao": "Champions League","league": 2,   "rebaix": None, "promo": None},
}

# ----------------------------------------------------------------------
# CHAMADA GENÉRICA
# ----------------------------------------------------------------------
def _get(endpoint, params):
    resp = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    time.sleep(PAUSA)
    if data.get("errors"):
        print(f"[AVISO] {endpoint}: {data['errors']}")
    return data.get("response", [])


# ----------------------------------------------------------------------
# STATUS (subiu da C / desceu da A) — compara as ligas entre temporadas
# ----------------------------------------------------------------------
def _ids_liga(league_id, season):
    if not league_id:
        return set()
    standings = _get("standings", {"league": league_id, "season": season})
    ids = set()
    if standings:
        for grupo in standings[0]["league"]["standings"]:
            for linha in grupo:
                ids.add(linha["team"]["id"])
    return ids


def _mapa_status(liga):
    """Retorna {team_id: 'subiu-c'|'desceu-a'|'normal'} para a liga atual."""
    atuais = _ids_liga(liga["league"], ANO)
    veio_de_cima = _ids_liga(liga["rebaix"], ANO - 1) if liga["rebaix"] else set()
    veio_de_baixo = _ids_liga(liga["promo"], ANO - 1) if liga["promo"] else set()
    status = {}
    for tid in atuais:
        if tid in veio_de_cima:
            status[tid] = "desceu-a"
        elif tid in veio_de_baixo:
            status[tid] = "subiu-c"
        else:
            status[tid] = "normal"
    return status


# ----------------------------------------------------------------------
# HISTÓRICO 30 JOGOS / 3 ANOS
# ----------------------------------------------------------------------
def _ultimos_30(league_id, team_id):
    jogos = []
    for season in TEMPORADAS_3_ANOS:
        jogos.extend(_get("fixtures", {"league": league_id, "season": season, "team": team_id, "status": "FT"}))
        if len(jogos) >= 30:
            break
    jogos.sort(key=lambda f: f["fixture"]["date"], reverse=True)
    return jogos[:30]


def _historico_time(league_id, team_id, status):
    jogos = _ultimos_30(league_id, team_id)
    V = E = D = 0
    gp = gc = 0
    forma = []
    for f in jogos:
        gh = f["goals"]["home"] or 0
        ga = f["goals"]["away"] or 0
        if f["teams"]["home"]["id"] == team_id:
            meus, deles = gh, ga
        else:
            meus, deles = ga, gh
        gp += meus
        gc += deles
        if meus > deles:
            V += 1; forma.append("V")
        elif meus == deles:
            E += 1; forma.append("E")
        else:
            D += 1; forma.append("D")

    if status == "subiu-c":
        tend = "Em ascensão"
    elif status == "desceu-a":
        tend = "Forte, readaptando"
    else:
        tend = "Em alta" if forma[:5].count("V") >= 3 else "Estável"

    medias = _medias_time(league_id, team_id)
    return {
        "status": status, "jogos30": len(jogos), "V": V, "E": E, "D": D,
        "golsPro": gp, "golsContra": gc,
        "cartoes": medias["cartoes_total"],
        "ult5": " ".join(forma[:5]) if forma else "—",
        "tendencia": tend,
        # médias por jogo — usadas para preencher a previsão de cada jogo
        "_medias": medias,
    }


def _medias_time(league_id, team_id):
    """
    Puxa as médias reais do time na temporada (por jogo):
      - cartões amarelos totais e média por jogo
      - gols marcados por jogo
      - gols sofridos por jogo (útil pra ajustar previsão do adversário)
    Escanteios e chutes ao gol NÃO vêm no endpoint de stats do time
    (a API-Football só fornece esses no nível de FIXTURE, jogo a jogo).
    Por isso usamos valores neutros baseados nas médias tipicas de cada liga.
    """
    resp = _get("teams/statistics", {"league": league_id, "season": ANO, "team": team_id})
    if not resp:
        return {"cartoes_total": 0, "cartoes_media": 1.9, "gols_pro_media": 1.2,
                "gols_con_media": 1.2, "escanteios_media": 5.0, "chutes_media": 4.5}

    # cartões amarelos totais (todas as faixas de minuto somadas)
    total_cart = 0
    for faixa in (resp.get("cards", {}).get("yellow", {}) or {}).values():
        if isinstance(faixa, dict) and faixa.get("total"):
            total_cart += faixa["total"]

    # jogos disputados na temporada
    jogos_totais = ((resp.get("fixtures", {}) or {}).get("played", {}) or {}).get("total") or 1

    # médias por jogo (gols vêm diretos da API; escanteios/chutes são estimativas típicas)
    gols_pro = ((resp.get("goals", {}) or {}).get("for", {}) or {}).get("average", {}) or {}
    gols_con = ((resp.get("goals", {}) or {}).get("against", {}) or {}).get("average", {}) or {}
    try:
        gp_med = float(str(gols_pro.get("total") or 1.2).replace(",", "."))
    except (TypeError, ValueError):
        gp_med = 1.2
    try:
        gc_med = float(str(gols_con.get("total") or 1.2).replace(",", "."))
    except (TypeError, ValueError):
        gc_med = 1.2

    return {
        "cartoes_total": total_cart,
        "cartoes_media": round(total_cart / max(jogos_totais, 1), 2),
        "gols_pro_media": round(gp_med, 2),
        "gols_con_media": round(gc_med, 2),
        # escanteios e chutes ao gol: médias tipicas do futebol europeu/brasileiro por time
        # (a API-Football não fornece isso no endpoint de time; viria só jogo a jogo).
        # Deixamos uma linha de base honesta ao invés de zero.
        "escanteios_media": 5.0,
        "chutes_media": 4.5,
    }


# ----------------------------------------------------------------------
# CONFRONTO DIRETO (H2H)
# ----------------------------------------------------------------------
def _h2h(a_id, b_id, a_nome, b_nome):
    resp = _get("fixtures/headtohead", {"h2h": f"{a_id}-{b_id}", "last": 5})
    placares = []
    va = vb = emp = 0
    for f in resp:
        gh = f["goals"]["home"] or 0
        ga = f["goals"]["away"] or 0
        casa = f["teams"]["home"]; fora = f["teams"]["away"]
        placares.append(f"{casa['name']} {gh}x{ga} {fora['name']}")
        venc = casa["id"] if gh > ga else fora["id"] if ga > gh else None
        if venc == a_id: va += 1
        elif venc == b_id: vb += 1
        else: emp += 1
    lider = f"{a_nome} leva vantagem" if va > vb else f"{b_nome} leva vantagem" if vb > va else "Equilíbrio total"
    return {"resumo": f"{va}V {a_nome} · {emp}E · {vb}V {b_nome}", "placares": placares[:4], "lider": lider}


# ----------------------------------------------------------------------
# JOGADORES (cartão, gols, chutes ao gol) — 30 vs 7 (a API entrega agregado da temporada)
# ----------------------------------------------------------------------
def _jogadores(league_id, team_id):
    jogadores = []
    pagina = 1
    while True:
        resp = requests.get(f"{BASE_URL}/players",
                            headers=HEADERS,
                            params={"team": team_id, "season": ANO, "league": league_id, "page": pagina},
                            timeout=25).json()
        time.sleep(PAUSA)
        jogadores.extend(resp.get("response", []))
        if pagina >= resp.get("paging", {}).get("total", 1):
            break
        pagina += 1

    cartao, gols, chutes, hist = [], [], [], {}
    for item in jogadores:
        p = item["player"]
        est = item["statistics"][0] if item["statistics"] else {}
        nome = p["name"]
        pos = (est.get("games", {}) or {}).get("position") or "—"
        jogos = (est.get("games", {}) or {}).get("appearences") or 0
        amarelos = (est.get("cards", {}) or {}).get("yellow") or 0
        g = (est.get("goals", {}) or {}).get("total") or 0
        assist = (est.get("goals", {}) or {}).get("assists") or 0
        faltas = (est.get("fouls", {}) or {}).get("committed") or 0
        chutes_gol = (est.get("shots", {}) or {}).get("on") or 0
        if not jogos:
            continue
        risco = round(min((amarelos / jogos) * 100, 99), 1)
        # 30 jogos = temporada (limit 30); 7 jogos = estimativa proporcional dos mais recentes
        g30 = min(jogos, 30)
        cartao.append({"name": nome, "pos": pos, "risco": f"{risco}%",
                       "motivo": "Alto risco" if risco > 15 else "Risco médio" if risco > 10 else "Muito seguro"})
        gols.append({"name": nome, "pos": pos, "g30": g, "g7": round(g * 7 / max(jogos, 1))})
        chutes.append({"name": nome, "pos": pos, "g30": chutes_gol, "g7": round(chutes_gol * 7 / max(jogos, 1))})
        hist[nome] = {"jogos30": g30, "cartoes30": amarelos, "faltas90": round(faltas / jogos, 1),
                      "gols": g, "assist": assist, "ult5cart": "—",
                      "tendencia": "Alta" if risco > 15 else "Média" if risco > 10 else "Baixa"}
    return cartao, gols, chutes, hist


# ----------------------------------------------------------------------
# ÁRBITRO — histórico de cartões por jogo
# ----------------------------------------------------------------------
_cache_arbitro = {}

def _historico_arbitro(arbitro_nome, league_id):
    """Busca os últimos jogos do árbitro e calcula a média de cartões por jogo."""
    if not arbitro_nome:
        return {"nome": "Não informado", "media_cartoes": 3.8, "jogos": 0}
    if arbitro_nome in _cache_arbitro:
        return _cache_arbitro[arbitro_nome]

    # busca jogos do árbitro nessa liga na temporada atual
    resp = _get("fixtures", {
        "referee": arbitro_nome,
        "season": ANO,
        "league": league_id,
        "status": "FT",
    })

    total_cart = 0
    total_jogos = len(resp)
    for jogo in resp[:20]:  # últimos 20 jogos pra ter amostra boa
        fid = jogo["fixture"]["id"]
        stats = _get("fixtures/statistics", {"fixture": fid})
        for time_stats in stats:
            for stat in (time_stats.get("statistics") or []):
                if stat.get("type") in ("Yellow Cards",) and stat.get("value"):
                    try:
                        total_cart += int(stat["value"])
                    except (TypeError, ValueError):
                        pass

    media = round(total_cart / max(total_jogos, 1), 2) if total_jogos > 0 else 3.8
    resultado = {
        "nome": arbitro_nome,
        "media_cartoes": media,
        "jogos": total_jogos,
    }
    _cache_arbitro[arbitro_nome] = resultado
    return resultado


def _predicao(fixture_id):
    resp = _get("predictions", {"fixture": fixture_id})
    return resp[0] if resp else {}


def _slug(s):
    import unicodedata
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum())[:5]


# ----------------------------------------------------------------------
# MONTA UM CAMPEONATO no formato exato da v2.5
# ----------------------------------------------------------------------
def montar_campeonato(app_id, liga):
    print(f"  → {liga['nome']} ...")
    league_id = liga["league"]
    status_map = _mapa_status(liga)

    hoje = dt.date.today()
    fim = hoje + dt.timedelta(days=7)
    fixtures = _get("fixtures", {"league": league_id, "season": ANO,
                                 "from": hoje.isoformat(), "to": fim.isoformat()})

    jogos = []
    historicoTimes = {}
    h2hJogos = {}
    historicoJogadores = {}
    jogadoresCartao = {}
    jogadoresGols = {}
    jogadoresChutes = {}
    timesJogadores = []
    times_processados = set()

    for f in fixtures:
        fid = f["fixture"]["id"]
        casa = f["teams"]["home"]; fora = f["teams"]["away"]
        data = dt.datetime.fromisoformat(f["fixture"]["date"].replace("Z", "+00:00"))
        weekday = (data.weekday() + 1) % 7  # dom=0 ... sáb=6 (igual ao seletor do app)
        slug = f"{_slug(casa['name'])}-{_slug(fora['name'])}"

        pred = _predicao(fid)
        pct = (pred.get("predictions", {}) or {}).get("percent", {})
        try:
            p_casa = float(str(pct.get("home", "0")).replace("%", ""))
            p_fora = float(str(pct.get("away", "0")).replace("%", ""))
        except (TypeError, ValueError):
            p_casa = p_fora = 0.0

        # árbitro do jogo — ajusta previsão de cartões
        arbitro_nome = (f["fixture"].get("referee") or "").split(",")[0].strip()
        hist_arb = _historico_arbitro(arbitro_nome, league_id)
        # fator do árbitro: compara média dele com média geral (3.8 cartões/jogo)
        fator_arb = round(hist_arb["media_cartoes"] / 3.8, 3) if hist_arb["media_cartoes"] > 0 else 1.0

        # garante o histórico dos dois times ANTES de preencher o jogo
        # (as médias reais vêm daí)
        for t in (casa, fora):
            chave = t["name"].lower()
            if chave in historicoTimes:
                continue
            st = status_map.get(t["id"], "normal")
            historicoTimes[chave] = _historico_time(league_id, t["id"], st)
            if len(timesJogadores) < 4 and t["id"] not in times_processados:
                cart, gol, chu, hist = _jogadores(league_id, t["id"])
                jogadoresCartao[chave] = cart[:3]
                jogadoresGols[chave] = gol[:3]
                jogadoresChutes[chave] = chu[:3]
                historicoJogadores.update(hist)
                timesJogadores.append({"key": chave, "nome": t["name"]})
                times_processados.add(t["id"])

        # médias reais dos dois times (vindas de _medias_time)
        mA = historicoTimes[casa["name"].lower()]["_medias"]
        mB = historicoTimes[fora["name"].lower()]["_medias"]

        # Previsão de gols: média de gols pró combinada com gols sofridos do adversário
        gols_A = round((mA["gols_pro_media"] + mB["gols_con_media"]) / 2, 2)
        gols_B = round((mB["gols_pro_media"] + mA["gols_con_media"]) / 2, 2)

        # Previsão de cartões: média do time × fator do árbitro
        cart_A = round(mA["cartoes_media"] * fator_arb, 2)
        cart_B = round(mB["cartoes_media"] * fator_arb, 2)

        jogos.append({
            "day": weekday, "id": slug, "times": casa["name"], "times2": fora["name"],
            "hora": data.strftime("%H:%M"),
            "arbitro": hist_arb["nome"],
            "vitoria": [p_casa, p_fora],
            # médias reais ajustadas pelo árbitro
            "cartao":     [cart_A, cart_B],
            "gols":       [gols_A, gols_B],
            "escanteios": [mA["escanteios_media"], mB["escanteios_media"]],
            "chutes":     [mA["chutes_media"],    mB["chutes_media"]],
        })

        h2hJogos[slug] = _h2h(casa["id"], fora["id"], casa["name"], fora["name"])

    return {
        "nome": liga["nome"], "pais": liga["pais"], "flag": liga["flag"], "divisao": liga["divisao"],
        "jogos": jogos, "historicoTimes": historicoTimes, "h2hJogos": h2hJogos,
        "historicoJogadores": historicoJogadores, "jogadoresCartao": jogadoresCartao,
        "jogadoresGols": jogadoresGols, "jogadoresChutes": jogadoresChutes,
        "timesJogadores": timesJogadores,
    }


# ----------------------------------------------------------------------
# EXECUÇÃO: gera o arquivo pronto com TODOS os campeonatos
# ----------------------------------------------------------------------
def main():
    print("Gerando análises da semana para os 9 campeonatos...")
    campeonatos = {}
    for app_id, liga in LIGAS.items():
        try:
            campeonatos[app_id] = montar_campeonato(app_id, liga)
        except Exception as e:
            print(f"  [ERRO] {liga['nome']}: {e} — pulando este campeonato.")

    saida = {
        "gerado_em": dt.datetime.now().isoformat(),
        "campeonatos": campeonatos,
    }
    with open("campeonatos_prontos.json", "w", encoding="utf-8") as fp:
        json.dump(saida, fp, ensure_ascii=False, indent=2)

    total_jogos = sum(len(c["jogos"]) for c in campeonatos.values())
    print(f"\n✅ Pronto! {len(campeonatos)} campeonatos, {total_jogos} jogos no total.")
    print("   Arquivo: campeonatos_prontos.json")
    print("   Enviando para o Netlify...")

    _enviar_netlify()


def _enviar_netlify():
    """Envia o campeonatos_prontos.json para o GitHub Gist automaticamente."""
    gist_id = os.environ.get("GIST_ID", "4d4eff2eeef21711db4e15a4862a43c6")
    token   = os.environ.get("GITHUB_TOKEN", "")

    if not token:
        print("⚠️  GITHUB_TOKEN não definido — pulando envio.")
        return

    try:
        with open("campeonatos_prontos.json", "r", encoding="utf-8") as f:
            conteudo = f.read()

        resp = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "files": {
                    "campeonatos_prontos.json": {
                        "content": conteudo
                    }
                }
            },
            timeout=30,
        )

        if resp.status_code == 200:
            print("✅ campeonatos_prontos.json enviado pro GitHub Gist com sucesso!")
            print("   Dados disponíveis em: https://gist.githubusercontent.com/pedroordonez1399-debug/4d4eff2eeef21711db4e15a4862a43c6/raw/campeonatos_prontos.json")
        else:
            print(f"⚠️  GitHub respondeu {resp.status_code}: {resp.text[:300]}")

    except Exception as e:
        print(f"⚠️  Erro ao enviar pro Gist: {e}")


if __name__ == "__main__":
    if API_KEY in ("", "COLE_SUA_CHAVE_AQUI"):
        raise SystemExit("⚠️  Defina APISPORTS_KEY com sua chave da API-Football.")
    main()
