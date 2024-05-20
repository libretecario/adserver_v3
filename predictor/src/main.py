from js import Request, Response
import json
from collections import defaultdict
from base64 import standard_b64decode
from urllib.parse import urlparse, parse_qs

model, roots, user_clusters, page_violations, site_violations, optimized_floors_sites, optimized_floors_roots = None, None, None, None, None, None, None

def any_root():
    return roots["any"]

def median_user_cluster():
    return user_clusters["G0"]

VERY_LOW_CURBING = 1
LOW_CURBING = 0.9
MEDIUM_CURBING = 0.8
HIGH_CURBING = 0.6
VERY_HIGH_CURBING = 0.4
VERY_LOW_RAISING = 1
LOW_RAISING = 1.25
MEDIUM_RAISING = 1.5
HIGH_RAISING = 1.75
VERY_HIGH_RAISING = 2

async def on_fetch(request: Request, env):
    global model, roots, user_clusters, page_violations, site_violations, optimized_floors_sites, optimized_floors_roots
    try:
        request_url = urlparse(request.url)
        query = parse_qs(request_url.query)
        root_name = request_url.path.split("/")[-1] 
        if (
            request.method == "GET"
            and root_name is not None
            and "interstitial" in root_name
        ):
            return Response.new(json.dumps({"pdc": 0}, indent=0))
            
        if model is None:
            model = Predictor.from_kv('saved_model')

        def any_root():
            return roots["any"]
        
        def median_user_cluster():
            return user_clusters["G0"]

        if roots is None or page_violations is None or site_violations is None:
            await env.KV.put("roots", '{ "any": ["65","EE","BA",1.7476,0.5474,0,0.0663,1.5171,0.8448,1.722,4.035,0.69,1.34,1.52,0.21]}')
            await env.KV.put("user_clusters", '{ "G0": [0.46,0.0953,0.0663,0.2303,2.3727,0.36,0.08,0.09,0.09] }')
            await env.KV.put("page_violations", '{}')
            await env.KV.put("site_violations", '{}')
            await env.KV.put("optimized_floors_sites", '{}')
            await env.KV.put("optimized_floors_roots", '{}')
            roots = defaultdict(any_root, json.loads(await env.KV.get("roots")))
            user_clusters = defaultdict(median_user_cluster, json.loads(await env.KV.get("user_clusters")))
            page_violations = defaultdict(lambda: None, json.loads(await env.KV.get("page_violations")))
            site_violations = defaultdict(lambda: None, json.loads(await env.KV.get("site_violations")))
            optimized_floors_sites = defaultdict(lambda: None, json.loads(await env.KV.get("optimized_floors_sites")))
            optimized_floors_roots = defaultdict(lambda: None, json.loads(await env.KV.get("optimized_floors_roots")))

        if request.method == "POST":
            req_json = json.loads(await request.text())
            if (
                req_json
                and "TestPrediction" in req_json
                and req_json["TestPrediction"] is True
            ):
                prediction = model.predict([{
                    "Browser": req_json["Browser"],
                    "Country": req_json["Country"],
                    "CPM": req_json["CPM"],
                    "CTR": req_json["CTR"],
                    "Language": req_json["Language"],
                    "OS": req_json["OS"],
                    "RootMinCluster": req_json["RootMinCluster"],
                    "RootMeanCluster": req_json["RootMeanCluster"],
                    "RootMaxCluster": req_json["RootMaxCluster"],
                    "UserMeanClusterTest": req_json["UserMeanClusterTest"],
                    "BidDistance": req_json["BidDistance"],
                    "BidMedDistance": req_json["BidMedDistance"],
                    "BidStdDevDistance": req_json["BidStdDevDistance"],
                    "BidDensity": req_json["BidDensity"],
                    "UserClusterCPM": req_json["UserClusterCPM"],
                    "UserClusterBidDistance": req_json["UserClusterBidDistance"],
                    "UserClusterBidMedDistance": req_json["UserClusterBidMedDistance"],
                    "UserClusterBidDensity": req_json["UserClusterBidDensity"],
                }])
                return Response.new(json.dumps(
                    {"pdc": prediction[0]},
                    indent=0,
                ))
            else:
                return Response.new(json.dumps({"pdc": 0}, indent=0))
        elif (
            request.method == "GET"
            and query
            and "dsReferer" in query
            and "mlcu" in query
        ):
            page = standard_b64decode(query["dsReferer"][0]).decode("UTF-8")
            
            site = urlparse("https://" + page).netloc
            if (
                site_violations[site] is not None
                or page_violations[page] is not None
                or optimized_floors_sites[site] is not None
                or optimized_floors_roots[root_name] is not None
            ):
                return json.dumps({"pdc": 0, "pv": 1}, indent=0)
            root = roots[root_name]
            final_mlcu = (
                "G0" if query["mlcu"][0] == "null" else query["mlcu"][0]
            )
            user_cluster = user_clusters[final_mlcu]
            prediction = model.predict([{
                "Browser": query["mlbr"][0],
                "Country": request.cf.country,
                "CPM": root[3],
                "CTR": root[4],
                "Language": query["mlla"][0],
                "OS": query["mlos"][0],
                "RootMinCluster": root[0],
                "RootMeanCluster": root[1],
                "RootMaxCluster": root[2],
                "UserMeanClusterTest": final_mlcu,
                "BidDistance": root[7],
                "BidMedDistance": root[8],
                "BidStdDevDistance": root[9],
                "BidDensity": root[10],
                "UserClusterCPM": user_cluster[0],
                "UserClusterBidDistance": user_cluster[1],
                "UserClusterBidMedDistance": user_cluster[2],
                "UserClusterBidDensity": user_cluster[4],
            }])
            return Response.new(json.dumps(
                {
                    "pdc": prediction[0]
                    * waterfalling_curbing(root[5])
                    * underpredictions_raising(root[11]),
                },
                indent=0,
            ))
        else:
            return Response.new(json.dumps({"pdc": 0}, indent=0))
    except BaseException as err:
        return Response.new(json.dumps({"pdc": 0, "error": str(err)}, indent=0))
    
def underpredictions_raising(underpredictions):
    if underpredictions is None or underpredictions <= 0.25:
        return VERY_LOW_RAISING
    if underpredictions <= 0.5:
        return LOW_RAISING
    if underpredictions <= 0.75:
        return MEDIUM_RAISING
    if underpredictions <= 1:
        return HIGH_RAISING
    return VERY_HIGH_RAISING


def waterfalling_curbing(waterfalling):
    if waterfalling is None or waterfalling <= 0.25:
        return VERY_LOW_CURBING
    if waterfalling <= 0.5:
        return LOW_CURBING
    if waterfalling <= 0.75:
        return MEDIUM_CURBING
    if waterfalling <= 1:
        return HIGH_CURBING
    return VERY_HIGH_CURBING

class Predictor:
    def __init__(self, model):
        self.kv_key = model

    @classmethod
    def from_kv(cls, model_name):
        return cls(model_name)

    def predict(self, data):
        return [10]
