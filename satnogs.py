from datetime import datetime, timedelta
import requests
from tqdm import tqdm
from flask import Flask , render_template,redirect,url_for, request
import json
from collections import defaultdict
import random
from apscheduler.schedulers.background import BackgroundScheduler
from satnogs_api_client import fetch_satellites
from satnogs_api_client.satnogs_api_client import DB_BASE_URL, get_paginated_endpoint
from skyfield.api import EarthSatellite, utc, load
import numpy

scheduler = BackgroundScheduler()
app = Flask(__name__)
	
ts = load.timescale(True)


Observations = defaultdict(list)
Passes = defaultdict(list)
Stations = []
StationsByID = {}
TLEs = defaultdict(list)
Transmitters = defaultdict(dict)
Raw_Transmitters = {}
StationsPasses = defaultdict(list)
SatDescrip = defaultdict(str)
CZMLOnline = []
CZMLTesting = []
CZMLOffline = []
CZMLStations = {}
TransmitterStats = []

def getFuture():
    print("Getting future Passes")
    global Observations
    global TLEs
    global StationsPasses
    norads = {}
    TLEs = defaultdict(list)
    StationsPasses = defaultdict(list)
    observations = defaultdict(dict)
    Start = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S%z')
    End = (datetime.utcnow() + timedelta(hours = 24)).replace(tzinfo=utc)
    passes = get_paginated_endpoint("https://network.satnogs.org/api/jobs/")
   # print("Started")
   # obs = get_paginated_endpoint("https://network.satnogs.org/api/observations/?end="+End+"&format=json&start="+Start)
   # for x in obs:
   #     norads[x["id"]] = x["noard_cat_id"]
    Observations = defaultdict(list)
    for x in tqdm(passes):
        if x["ground_station"] == None:
            continue
        #if x["id"] in observations:
        #noard = norads[x["id"]]
        try:
            if(not x["transmitter"] in Raw_Transmitters.keys()):
                print(x["transmitter"])
                continue
            sat_id = Raw_Transmitters[x["transmitter"]]["sat_id"]
            start = datetime.strptime(x["start"], '%Y-%m-%dT%H:%M:%Sz')
            start = start.replace(tzinfo=utc)
            #print(start,End)
            if (start > End):
                #print("Skipped obs: ",str(x["id"]))
                continue
            end = datetime.strptime(x["end"], '%Y-%m-%dT%H:%M:%Sz')
            end = end.replace(tzinfo=utc)
                # "transmitter":Transmitters[observations[x["id"]]["norad_cat_id"]][x["transmitter"]]
            if start < end:
                Observations[sat_id].append({"station": x["ground_station"], "transmitter": Transmitters[x["transmitter"]], "start": start, "end": end, "id": x["id"]})
                TLEs[sat_id] = EarthSatellite(x["tle1"], x["tle2"],x["tle0"])
                StationsPasses[x["ground_station"]].append({"sat_id": sat_id, "transmitter": Transmitters[x["transmitter"]], "start": start, "end": end, "id": x["id"]})
                if not sat_id in SatDescrip:
                    updateTransmitters()
                if not x["ground_station"] in StationsByID.keys():
                    updateStations()
        except Exception as e:
            print("Error on observation number: " + str(x["id"]) + "  " + str(e) + "\n" + "RAW :" + str(x))

    del observations
    del passes
    del End
    del Start                
    print(str(len(Observations))+" Future passes found.")


 
def GetGroundStations():
    print("Getting Ground Stations")
    stations = get_paginated_endpoint("https://network.satnogs.org/api/stations/")
    for x in tqdm(stations):
        StationsByID[x["id"]] = x
    return stations


def FindPasses(observations_):
    print("Finding Future Passes")
    observations = observations_.copy()
    passses = []
    observation = observations.pop(0)
    for x in observations:
        if x["end"] >= observation["start"]:
            observation["start"] = x["start"]
        else:
            if (observation["start"] - x["end"]).total_seconds() < 120:
                observation["start"] = x["start"]
            else:
                passses.append(observation)
                observation = x
    passses.append(observation)
    print("Finished Finding Future Passes")
    return passses    
    
   

@scheduler.scheduled_job('interval', days=0.5)
def updateTransmitters():
    global Transmitters
    global SatDescrip 
    SatDescrip = {}
    Transmitters = defaultdict(dict)
    print("Updating Transmitters")
    temp = requests.get("https://db.satnogs.org/api/transmitters/",headers={'User-Agent': 'KD9KCK Satnogs Map'}).json()
    for x in temp:
        Raw_Transmitters[x["uuid"]] = x
        Transmitters[x["uuid"]] = [x["description"], [random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255]]
        SatDescrip[x["sat_id"]] = ""
    #for x in Transmitters.keys():
    for x in temp:
        SatDescrip[x["sat_id"]] += '<div class="trans" style="background-color:#'+str("%02x" % Transmitters[x["uuid"]][1][0])+str("%02x" % Transmitters[x["uuid"]][1][1])+str("%02x" % Transmitters[x["uuid"]][1][2])+'";>'+Transmitters[x["uuid"]][0]+'</div>'
    print("Finished Updating Transmitters")
    updateTransmitterStats()

   
def updateTransmitterStats():
    print("Updating Transmitter Stats")
    global TransmitterStats
    TransmitterStats = []
    transmitterStats = get_paginated_endpoint("https://network.satnogs.org/api/transmitters/")
    satellites = requests.get("https://db.satnogs.org/api/satellites/",headers={'User-Agent': 'KD9KCK Satnogs Map'}).json()
    sats = {}
    for x in satellites:
        sats[x["sat_id"]] = x
    for x in transmitterStats:
        try:
            transmitter = Raw_Transmitters[x["uuid"]]
            stat = x["stats"]
            sat = sats[transmitter["sat_id"]]
            stat["transmitter_name"] = transmitter["description"]
            stat["sat_name"] = sat["name"]
            stat["norad"] = transmitter["norad_cat_id"]
            TransmitterStats.append(stat)
        except:
            pass
    TransmitterStats.sort(key=lambda x: (x["total_count"],x["success_rate"]),reverse = True)
    print("Finished Updating Transmitter Stats")
    
    
@scheduler.scheduled_job('interval', minutes=15)#hours=1)
def updatePasses():
    getFuture()
    updateCZML()
   # total = 0
   # for x in StationsPasses.keys():
  #      total+=len(StationsPasses[x])
  #  print("Total StationsPassses: " +str(total))
 #   print("Total TLE: "+str(len(TLEs)))
#    print("Total Passes: "+str(len(Passes)))
    #print("Total StationsPasses: "+str(len(StationsPasses)))
#    all_objects = muppy.get_objects()
#    sum1 = summary.summarize(all_objects)
#    summary.print_(sum1)
#    del all_object
#    del sum1

@scheduler.scheduled_job('interval', hours=1)
def updateStations():
    global Stations
    Stations = GetGroundStations()


#@scheduler.scheduled_job('interval', minutes=5)
def updateCZML():
    #print(SatDescrip.keys())
    print("Updating CZML")
    global CZMLOnline
    global CZMLOffline
    global CZMLTesting
    global CZMLStations
    CZMLOffline = []
    CZMLOnline = []
    CZMLTesting = []
    CZMLStations = {}
    onlineDoc = {"id":"document","name":"Online","version":"1.0","clock":{"interval":"0000-00-00T00:00:00Z/9999-12-31T24:00:00Z","step":"SYSTEM_CLOCK"}}
    offlineDoc = {"id":"document","name":"Offline","version":"1.0","clock":{"interval":"0000-00-00T00:00:00Z/9999-12-31T24:00:00Z","step":"SYSTEM_CLOCK"}}
    testingDoc = {"id":"document","name":"Testing","version":"1.0","clock":{"interval":"0000-00-00T00:00:00Z/9999-12-31T24:00:00Z","step":"SYSTEM_CLOCK"}}
    CZMLOffline.append(offlineDoc)
    CZMLOnline.append(onlineDoc)
    CZMLTesting.append(testingDoc)
    
    for x in Stations:
        color = [0, 230, 64, 255]
        if x["status"] == "Testing":
            color = [248, 148, 6, 255]
        if x["status"] == "Offline":
            color = [255, 0, 0, 50]

        station = {}
        station["id"] = str(x["id"])
        station["name"] = x["name"]
        station["point"] = {}
        station["show"] = True
        station["point"]["color"] = {}
        station["point"]["color"]["rgba"] = color
        station["point"]["outlineColor"] = {}
        station["point"]["outlineColor"]["rgba"] = [255, 255, 255, color[3]]
        station["point"]["outlineWidth"] = 2.0
        station["position"] = {}
        station["point"]["pixelSize"] = 7.0
        station["position"]["cartographicDegrees"] = [x["lng"], x['lat'], x["altitude"]]
        station["description"] = "<b>ID: "+str(x["id"]) + "</b><br><b>Total Observations: "
        station["description"] += str(x["observations"]) + "</b><br><b>Status: " + x["status"] + "</b><br><b>QTH: "
        station["description"] += x["qthlocator"] + "</b><br></b>Description: </b>" + x["description"]
        if x["status"] == "Testing":
            CZMLTesting.append(station)
        else:
            if x["status"] == "Offline":
                CZMLOffline.append(station)
            else:
                CZMLOnline.append(station)
        CZMLStations[str(x["id"])] = []
        CZMLStations[str(x["id"])].append({"id":"document","name":x["name"],"version":"1.0","clock":{"interval":"0000-00-00T00:00:00Z/9999-12-31T24:00:00Z","step":"SYSTEM_CLOCK"}})
        CZMLStations[str(x["id"])].append(station)
    AliveSats = []
    for x in Observations.keys():
        for y in Observations[x]:
            sat = {}
            sat["id"] = str(y["id"])
            sat["name"] = TLEs[x].name
            sat["show"] = True
            sat["billboard"] = {"image": "static/sat.png", "scale": 0.50}
            sat["position"] = {}
            sat["position"]["cartographicDegrees"] = []
           # print(y)
            sat["description"] = SatDescrip[x]
            temp = y["start"]
            time = 0
            sat["position"]["interpolationAlgorithm"] = "LAGRANGE"
            sat["position"]["interpolationDegree"] = 5
            sat["position"]["epoch"] = (y["start"].isoformat()+"Z").replace("+00:00", "")
            sat["path"] = {"show": {"interval": (y["start"].isoformat()+"Z").replace("+00:00", "") + "/" + ((y["end"]).isoformat()+"Z").replace("+00:00", ""), "boolean": True}, "width": 2, "material": {"solidColor": {"color": {"rgba": [0, 255, 0, 255]}}}, "leadTime": 100000, "trailTime": 100000}
            
            while temp <= y["end"] + timedelta(seconds=1):
                subpoint = TLEs[x].at(ts.utc(temp)).subpoint()
                lat = subpoint.latitude.degrees
                lng = subpoint.longitude.degrees
                if numpy.isnan(lat):
                    break
                elevation = subpoint.elevation.m
                sat["position"]["cartographicDegrees"].extend([time, lng, lat, elevation])
                time += 60*3
                temp = temp + timedelta(minutes=3)
            else:
                try:
 #               print(StationsByID)
#                print(y["station"])
                    if StationsByID[y["station"]]["status"] =="Testing":
                        CZMLTesting.append(sat)
                    else:
                        if StationsByID[y["station"]]["status"] == "Offline":
                            CZMLOffline.append(sat)
                        else:
                            CZMLOnline.append(sat)
                except:
                    print(y)
                    print(StationsByID[y["station"]])
                AliveSats.append(str(y["id"]))
                try:
                    CZMLStations[str(y["station"])].append(sat)
                except Exception as e:
                    print(e)
            
    for x in Observations.keys():
        for y in Observations[x]:
            if str(y["id"]) in AliveSats:
                sat = {}
                sat["id"] = str(y["id"])+"Link"
                sat["polyline"] = {"show": {"interval": (y["start"].isoformat()+"Z").replace("+00:00", "")+"/"+((y["end"]+timedelta(seconds=1)).isoformat()+"Z").replace("+00:00", ""), "boolean": True}, "width": 2, "material": {"solidColor": {"color": {"rgba": y["transmitter"][1]}}}, "followSurface": False, "positions": {"references": [str(y["id"])+"#position", str(y["station"]) + "#position"]}}
                if StationsByID[y["station"]]["status"] =="Testing":
                    CZMLTesting.append(sat)
                else:
                    if StationsByID[y["station"]]["status"] == "Offline":
                        CZMLOffline.append(sat)
                    else:
                        CZMLOnline.append(sat)
                try:
                    CZMLStations[str(y["station"])].append(sat)
                except:
                    pass
    print("Finished Updating CZML")

@app.route("/")
def index():
    return render_template("index.html",url="/czml")

@app.route("/rotating")
def rotating():
    speed = request.args.get('speed', default = '30', type = str) 
    return render_template("rotating.html",url="/czml",speed=speed)


@app.route("/station/<int:station_id>")
def station(station_id):
    return render_template("station.html",url="/czml",station=str(station_id))
    
@app.route("/czml")
def api_czml():
    return json.dumps(CZMLOnline)
    
@app.route("/czmlstation/<int:station_id>")
def api_czmlstation(station_id):
    return json.dumps(CZMLStations[str(station_id)])

@app.route("/czmloff")
def api_czmloff():
    return json.dumps(CZMLOffline)

@app.route("/czmltest")
def api_czmltest():
    return json.dumps(CZMLTesting)    

@app.route("/transmitterstats")
def transmitterStats():
    return render_template("transmitterstats.html",stats=TransmitterStats)



updateStations()
updateTransmitters()
getFuture()
updateCZML()
scheduler.start()
# app.run(use_reloader=False, host="0.0.0.0", port=3001)
if __name__ == '__main__':  
   app.run()
