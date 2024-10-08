# youtube-to-m3u
Play YouTube live streams in any player

## Requirements
python <br>
flask (can be installed by doing pip install flask) <br>
[streamlink](https://streamlink.github.io/install.html) (available at path)

## How To Use
Open youtubelive.m3u <br>
Change the ip address in the streamlink to the ip address of the machine running the script <br>
You can also change the port but if you do this you must change the port to match at the bottom of youtube-live.py <br>
<br>
To add other live streams just add into m3u in the following format 

```
#EXTINF:-1 tvg-name="Channel Name" tvg-id="24.7.Dummy.us" tvg-logo="https://upload.wikimedia.org/wikipedia/commons/thumb/5/54/YouTube_dark_logo_2017.svg/2560px-YouTube_dark_logo_2017.svg.png" group-title="YouTube",Channel Name
http://192.168.1.123:6095/stream?url=https://www.youtube.com/@ChannelName/live
```

Or if the channel has multiple live streams you can use the /watch? link however these links will change if the channel stops and restarts broadcast <br>
<br>
You can change tvg-name tvg-logo group-title and channel name and if you want to link to an epg change tvg-id to match your epgs tvg-id for that channel <br>
(The two sample streams link to the epg from epgshare01.online UK and USA epgs) <br>
<br>
Run the python script <br>
python youtube-live.py or python3 youtube-live.py if you have the old python2 installed <br>
<br>
Script must be running for the m3u to work
