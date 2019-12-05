from resources.lib.globals import *
from resources.lib.classes.auth import Auth

class MyMonitor(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
        self.action = kwargs['action']

    def onSettingsChanged(self):
        log('MyMonitor.onSettingsChanged() triggered....')
        log('Setting update_guide: %s' % SETTINGS.getSetting('update_guide'))
        if SETTINGS.getSetting('update_guide') == 'true':
            self.action()

class Slinger(object):

    Channels_Updated = 0
    Guide_Updated = 0
    Shows_Updated = 0
    On_Demand_Updated = 0
    VOD_Updated = 0

    Seconds_Per_Hour = 60 * 60
    Channels_Interval = 168 * Seconds_Per_Hour  # One Week
    Guide_Interval = 12 * Seconds_Per_Hour  # Twelve Hours
    Shows_Interval = 168 * Seconds_Per_Hour  # One Week
    On_Demand_Interval = 168 * Seconds_Per_Hour  # One Week
    VOD_Interval = 12 * Seconds_Per_Hour  # Twelve Hours
    Guide_Days = 1
    EPG_Path = os.path.join(xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile')), 'sling_epg.xml')
    Playlist_Path = os.path.join(xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile')), 'sling_playlist.m3u')

    Monitor = None
    Auth = None
    DB = None
    EndPoints = None
    Force_Guide_Update = False

    def __init__(self):
        global USER_SUBS, USER_DMA, USER_OFFSET
        log('Slinger function:  __init__')
        # self.Monitor = xbmc.Monitor()
        self.Monitor = MyMonitor(action=self.updateGuide)

        self.EndPoints = self.buildEndPoints()
        self.Auth = Auth()
        loginURL = '%s/sling-api/oauth/authenticate-user' % self.EndPoints['micro_ums_url']
        loggedIn, message = self.Auth.logIn(loginURL, USER_EMAIL, USER_PASSWORD)
        log("__init__: logIn() ==> Success: " + str(loggedIn) + " | Message: " + message)
        if loggedIn:
            log("__init__: self.user Subscriptions URL => " + USER_INFO_URL)
            gotSubs, message = self.Auth.getUserSubscriptions(USER_INFO_URL)
            log("__init__: self.user Subscription Attempt, Success => " + str(gotSubs) + "Message => " + message)
            self.Auth.getAccessJWT(self.EndPoints)
            if gotSubs:
                USER_SUBS = message

                success, region = self.Auth.getRegionInfo()
                if not success:
                    log("__init__: Failed to get User Region Info, exiting.")
                    self.close()

                USER_DMA = region['USER_DMA']
                USER_OFFSET = region['USER_OFFSET']
            else:
                log("__init__: Failed to get User Subscriptions, exiting.")
                self.close()

        if not xbmcvfs.exists(DB_PATH):
            self.createDB()
        self.DB = sqlite3.connect(DB_PATH)

        if self.DB is not None:
            self.main()
        else:
            log('Slinger __init__: Failed to initialize DB, closing.')
            self.close()

    def main(self):
        log('Slinger function: main()')

        self.checkLastUpdate()
        self.checkUpdateIntervals()

        while not self.Monitor.abortRequested():
            timestamp = int(time.time())

            if (self.Channels_Updated + self.Channels_Interval) < timestamp:
                self.updateChannels()
            if (self.Guide_Updated + self.Guide_Interval) < timestamp:
                self.updateGuide()
            if (self.On_Demand_Updated + self.On_Demand_Interval) < timestamp:
                self.updateOnDemand()
            if (self.Shows_Updated + self.Shows_Interval) < timestamp:
                self.updateShows()
            if (self.VOD_Updated + self.VOD_Interval) < timestamp:
                self.updateVOD()

            # Sleep for 30 minutes or exit on break
            if self.Monitor.waitForAbort(1800):
                log("shutting down slinger service...")
                break

            self.checkLastUpdate()
            self.checkUpdateIntervals()

        self.close()

    def checkForceUpdate(self):
        log('Slinger function: checkForceUpdate()')
        if SETTINGS.getSetting('update_guide') == 'true':
            log('checkForceUpdate(): Setting Force_Guide_Update flag')
            self.Force_Guide_Update = True

    def clearForceUpdate(self):
        log('Slinger function: clearForceUpdate()')
        SETTINGS.setSetting('update_guide', 'false')

    def checkLastUpdate(self):
        log('Slinger function: checkLastUpdate()')
        result = False  # Return False if something needs updated, else True

        query = "SELECT \
                (SELECT Last_Update FROM Channels ORDER BY Last_Update ASC LIMIT 1, 1) AS Channels_Last_Update, \
                (SELECT Last_Update FROM Guide ORDER BY Last_Update ASC LIMIT 1, 1) AS Guide_Last_Update, \
                (SELECT Last_Update FROM Shows ORDER BY Last_Update ASC LIMIT 1, 1) AS Shows_Last_Update, \
                (SELECT Last_Update FROM On_Demand_Folders ORDER BY Last_Update ASC LIMIT 1, 1) AS On_Demand_Last_Update, \
                (SELECT Last_Update FROM VOD_Assets ORDER BY Last_Update ASC LIMIT 1, 1) AS VOD_Last_Update"

        try:
            cursor = self.DB.cursor()
            cursor.execute(query)
            updates = cursor.fetchone()
            if updates is not None and len(updates) > 0:
                self.Channels_Updated = updates[0] if updates[0] is not None else 0
                self.Guide_Updated = updates[1] if updates[1] is not None else 0
                self.Shows_Updated = updates[2] if updates[2] is not None else 0
                self.On_Demand_Updated = updates[3] if updates[3] is not None else 0
                self.VOD_Updated = updates[4] if updates[4] is not None else 0

                log('checkLastUpdate(): Last Updates => Channels: %i | Guide: %i | Shows: %i | On Demand: %i | VOD: %i' %
                    (self.Channels_Updated, self.Guide_Updated, self.Shows_Updated, self.On_Demand_Updated,
                     self.VOD_Updated))

                result = True
        except sqlite3.Error as err:
            log('checkLastUpdate(): Failed to read Last Update times from DB, error => %s' % err)
        except Exception as exc:
            log('checkLastUpdate(): Failed to read Last Update times from DB, exception => %s' % exc)

        return result

    def checkUpdateIntervals(self):
        log('Slinger function: checkUpdateIntervals()')

        self.Channels_Interval = int(SETTINGS.getSetting('Channels_Interval')) * 24 * self.Seconds_Per_Hour
        self.Guide_Interval = int(SETTINGS.getSetting('Guide_Interval')) * 24 * self.Seconds_Per_Hour
        self.Shows_Interval = int(SETTINGS.getSetting('Shows_Interval')) * 24 * self.Seconds_Per_Hour
        self.On_Demand_Interval = int(SETTINGS.getSetting('On_Demand_Interval')) * 24 * self.Seconds_Per_Hour
        self.VOD_Interval = int(SETTINGS.getSetting('Shows_Interval')) * 24 * self.Seconds_Per_Hour
        self.Guide_Days = int(SETTINGS.getSetting('Guide_Days'))

        log('checkUpdateIntervals(): Updated Intervals => Channels: %i | Guide: %i | Shows: %i | On Demand: %i | VOD: %i' %
            (self.Channels_Interval, self.Guide_Interval, self.Shows_Interval, self.On_Demand_Interval,
             self.VOD_Interval))

    def updateChannels(self):
        log('Slinger function: updateChannels()')
        result = False
        channels = {}

        subs = binascii.b2a_base64(str.encode(LEGACY_SUBS.replace('+', ','))).decode().strip()
        channels_url = '%s/cms/publish3/domain/channels/v4/%s/%s/%s/1.json' % \
                       (self.EndPoints['cms_url'], USER_OFFSET, USER_DMA, subs)
        log('updateChannels()\r%s' % channels_url)
        response = requests.get(channels_url, headers=HEADERS, verify=VERIFY)
        if response is not None and response.status_code == 200:
            response = response.json()
            if 'subscriptionpacks' in response:
                sub_packs = response['subscriptionpacks']
                for sub_pack in sub_packs:
                    if 'channels' in sub_pack:
                        channel_count = 0
                        progress = xbmcgui.DialogProgressBG()
                        progress.create('Sling TV')
                        progress.update(0, 'Downloading Channel Info...')
                        for channel in sub_pack['channels']:
                            channels[channel['channel_guid']] = Channel(channel['channel_guid'], self.EndPoints,
                                                                        self.DB, update=True)
                            channel_count += 1
                            progress.update(int((float(channel_count) / len(sub_pack['channels'])) * 100))
                            if self.Monitor.abortRequested():
                                break
                        progress.close()

        query = "SELECT GUID FROM Channels"
        try:
            cursor = self.DB.cursor()
            cursor.execute(query)
            db_channels = cursor.fetchall()
            if db_channels is not None and len(db_channels) > 0:
                delete_query = ''
                for channel in db_channels:
                    guid = channel[0]
                    if guid not in channels:
                        temp_query = "DELETE FROM Channels WHERE GUID = '%s'" % guid
                        delete_query = '%s; %s' % (delete_query, temp_query) if delete_query != '' else temp_query
                        log('Channel %s not in Subscription package, will DELETE.' % guid)
                if delete_query != '':
                    try:
                        cursor.executescript(delete_query)
                        self.DB.commit()
                        result = True
                    except sqlite3.Error as err:
                        log('updateChannels(): Failed to delete extra channels from DB, error => %s' % err)
                    except Exception as exc:
                        log('updateChannels(): Failed to delete extra channels from DB, exception => %s' % exc)
                else:
                    result = True
        except sqlite3.Error as err:
            log('updateChannels(): Failed to read Last Update times from DB, error => %s' % err)
        except Exception as exc:
            log('updateChannels(): Failed to read Last Update times from DB, exception => %s' % exc)

        return result

    def updateGuide(self):
        log('Slinger function: updateGuide()')
        result = False

        self.checkForceUpdate()

        log('updateGuide(): Guide Days %i' % self.Guide_Days)
        for day in range(0, self.Guide_Days):  #Range is non-inclusive
            timestamp = timeStamp(datetime.date.today() + datetime.timedelta(days=day))
            url_timestamp = (datetime.date.today() + datetime.timedelta(days=day)).strftime("%y%m%d") + \
                            USER_OFFSET.replace('-', '')
            log('updateGuide(): Timestamp: %i | URL Timestamp %s' % (timestamp, url_timestamp))
            current_timestamp = int(time.time())
            log('Start Timestamp: %i | Interval: %i' % (current_timestamp, self.Seconds_Per_Hour*24))
            query = "SELECT GUID, Poster FROM Channels"
            try:
                cursor = self.DB.cursor()
                cursor.execute(query)
                channels = cursor.fetchall()
                if channels is not None and len(channels):
                    progress = xbmcgui.DialogProgressBG()
                    progress.create('Sling TV')
                    progress.update(0, 'Downloading Day %i Guide Info...' % (day + 1))
                    channel_count = 0
                    for channel in channels:
                        channel_guid = channel[0]
                        channel_poster = channel[1]
                        query = "SELECT Last_Update FROM Guide WHERE Guide.Channel_GUID = '%s' " \
                                "ORDER BY Last_Update DESC LIMIT 1,1" % channel_guid
                        cursor.execute(query)
                        db_last_update = cursor.fetchone()
                        if db_last_update is not None and len(db_last_update):
                            last_update = db_last_update[0]
                        else:
                            last_update = current_timestamp - (60 * 60 * 24)
                        update_day = int(datetime.datetime.fromtimestamp(last_update).strftime('%d'))
                        today_day = int(datetime.datetime.fromtimestamp(current_timestamp).strftime('%d'))

                        if update_day < today_day or self.Force_Guide_Update:
                            schedule_url = "%s/cms/publish3/channel/schedule/24/%s/1/%s.json" % \
                                           (self.EndPoints['cms_url'], url_timestamp, channel_guid)
                            log('updateGuide(): Schedule URL =>\r%s' % schedule_url)
                            response = requests.get(schedule_url, headers=HEADERS, verify=VERIFY)
                            if response is not None and response.status_code == 200:
                                channel_json = response.json()
                                if channel_json is not None:
                                    self.processSchedule(channel_guid, channel_poster,
                                                         channel_json['schedule'], timestamp)
                        channel_count += 1
                        progress.update(int((float(channel_count) / len(channels)) * 100))
                        if self.Monitor.abortRequested():
                            break
                    progress.close()
                result = True
            except sqlite3.Error as err:
                log('updateGuide(): Failed to retrieve channels from DB, error => %s' % err)
                result = False
            except Exception as exc:
                log('updateGuide(): Failed to retrieve channels from DB, exception => %s' % exc)
                result = False
        self.cleanGuide()

        if xbmc.getCondVisibility('System.HasAddon(pvr.iptvsimple)') and SETTINGS.getSetting('Enable_EPG') == 'true':
            self.buildPlaylist()
            self.buildEPG()
            self.checkIPTV()
            self.toggleIPTV()

        if self.Force_Guide_Update:
            self.clearForceUpdate()

        return result

    def processSchedule(self, channel_guid, channel_poster, json_data, timestamp):
        log('Slinger function: processSchedule()')
        result = False
        schedule = {}

        log('processSchedule(): Retrieving channel %s guide from Sling for %i' %
            (channel_guid, timestamp))
        if 'scheduleList' in json_data:
            for slot in json_data['scheduleList']:
                new_slot = {'Name': slot['title'] if 'title' in slot else '',
                            'Thumbnail': slot['thumbnail']['url'] if 'thumbnail' in slot else '',
                            'Poster': '',
                            'Rating': '',
                            'Genre': '',
                            'Start': int(slot['schedule_start'].split('.')[0]),
                            'Stop': int(slot['schedule_stop'].split('.')[0])}
                if 'metadata' in slot:
                    metadata = slot['metadata']
                    ratings = ''
                    if 'ratings' in metadata:
                        for rating in metadata['ratings']:
                            ratings = '%s, %s' % (ratings, rating) if len(ratings) > 0 else rating
                    new_slot['Rating'] = ratings
                    description = ''
                    if 'episode_season' in metadata:
                        description = 'S%i' % int(metadata['episode_season'])
                    if 'episode_number' in metadata:
                        if len(description) == 0:
                            description = 'E%i' % int(metadata['episode_number'])
                        else:
                            description = '%sE%i ' % (description, int(metadata['episode_number']))
                    if 'episode_title' in description:
                        if len(description) == 0:
                            description = metadata['episode_title']
                        else:
                            description = '%s%s' % (description, metadata['episode_title'])
                    if 'description' in metadata:
                        description = '%s %s' % (description, metadata['description'])
                    new_slot['Description'] = description
                    genres = ''
                    if 'genre' in metadata:
                        for genre in metadata['genre']:
                            genres = '%s, %s' % (genres, genre) if len(genres) > 0 else genre
                    new_slot['Genre'] = genres
                if 'program' in slot:
                    program = slot['program']
                    if 'background_image' in program:
                        if program['background_image'] is not None:
                            new_slot['Poster'] = program['background_image']['url']
                    else:
                        new_slot['Poster'] = channel_poster

                new_slot['Name'] = new_slot['Name'].strip()
                new_slot['Description'] = new_slot['Description'].strip()
                new_slot['Genre'] = new_slot['Genre'].strip()
                new_slot['Rating'] = new_slot['Rating'].strip().replace('_', ' ')

                schedule[new_slot['Start']] = new_slot
                self.saveSlot(channel_guid, new_slot)
        else:
            log('processSchedule(): scheduleList is empty, skipping.' )
        if len(schedule):
            result = True

        return result

    def saveSlot(self, channel_guid, new_slot):
        log('Slinger function: saveSlot()')

        timestamp = int(time.time())
        log('saveSlot(): Saving guide slot %s into DB for channel %s' % (new_slot['Name'], channel_guid))
        cursor = self.DB.cursor()

        try:
            slot_query = "REPLACE INTO Guide (Channel_GUID, Start, Stop, Name, Description, Thumbnail, Poster, " \
                         "Genre, Rating, Last_Update) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            cursor.execute(slot_query, (channel_guid, new_slot['Start'], new_slot['Stop'],
                                        new_slot['Name'].replace("'", "''"), new_slot['Description'].replace("'", "''"),
                                        new_slot['Thumbnail'], new_slot['Poster'], new_slot['Genre'],
                                        new_slot['Rating'], timestamp))
            self.DB.commit()
        except sqlite3.Error as err:
            log('saveSlot(): Failed to save slot %s to DB, error => %s\rJSON => %s' % (new_slot['Name'], err, json.dumps(new_slot, indent=4)))
        except Exception as exc:
            log('saveSlot(): Failed to save slot %s to DB, exception => %s\rJSON => %s' % (new_slot['Name'], exc, json.dumps(new_slot, indent=4)))

    def cleanGuide(self):
        log('Slinger function: cleanGuide()')

        timestamp = int(time.time()) - (60 * 60 * 12)
        query = "DELETE FROM Guide WHERE Stop < %i" % timestamp
        try:
            cursor = self.DB.cursor()
            cursor.execute(query)
            self.DB.commit()
        except sqlite3.Error as err:
            log('saveSlot(): Failed to clean guide in DB, error => %s' % err)
        except Exception as exc:
            log('saveSlot(): Failed to clean guide in DB, exception => %s' % exc)

    def getChannels(self):
        log('Slinger function: getChannels()')
        channels = []
        query = 'SELECT DISTINCT Channels.id, Channels.name, Channels.thumbnail, Channels.qvt_url, Channels.genre ' \
                'FROM Channels ' \
                'inner JOIN Guide on Channels.GUID = Guide.Channel_GUID order by Channels.Call_Sign asc'
        try:
            cursor = self.DB.cursor()
            cursor.execute(query)
            db_channels = cursor.fetchall()
            if db_channels is not None and len(db_channels):
                for row in db_channels:
                    id = str(row[0])
                    title = str(row[1]).replace("''", "'")
                    logo = str(row[2])
                    url = str(row[3])
                    genre = str(row[4])
                    channels.append([id, title, logo, url, genre])
        except sqlite3.Error as err:
            log('getChannels(): Failed to retrieve channels from DB, error => %s\rQuery => %s' % (err, query))
        except Exception as exc:
            log('getChannels(): Failed to retrieve channels from DB, exception => %s\rQuery => %s' % (exc, query))

        return channels

    def buildPlaylist(self):
        log('Slinger function: buildPlaylist()')
        m3u_file = xbmcvfs.File(self.Playlist_Path, 'w')
        m3u_file.write("#EXTM3U")
        m3u_file.write("\n")
        channels = self.getChannels()
        for channel_id, title, logo, url, genre in channels:
            m3u_file.write("\n")
            channel_info = '#EXTINF:-1 tvg-id="%s" tvg-name="%s"' % (channel_id, title)
            if logo is not None:
                channel_info += ' tvg-logo="%s"' % logo
            channel_info += ' group_title="Sling TV %s",%s' % (genre, title)
            m3u_file.write(channel_info + "\n")
            url = 'plugin://plugin.video.sling/?mode=play&url=%s' % url
            m3u_file.write(url + "\n")
            if self.Monitor.abortRequested():
                m3u_file.close()
                break

        m3u_file.close()

    def buildEPG(self):
        log('Slinger function: buildEPG()')
        master_file = xbmcvfs.File(self.EPG_Path, 'w')
        master_file.write('<?xml version="1.0" encoding="utf-8" ?>\n')
        master_file.write("<tv>\n")

        channels = self.getChannels()
        for channel_id, title, logo, url, genre in channels:
            master_file.write('<channel id="%s">\n' % channel_id)
            master_file.write('    <display-name lang="en">%s</display-name>\n' % title)
            master_file.write('</channel>\n')
            if self.Monitor.abortRequested():
                break

        query = "SELECT strftime('%Y%m%d%H%M%S',datetime(Guide.Start, 'unixepoch')) as start, " \
                "strftime('%Y%m%d%H%M%S',datetime(Guide.Stop, 'unixepoch')) as stop, " \
                "Channels.id, Guide.Name, '' AS sub_title, Guide.Description, Guide.Thumbnail, Guide.Genre " \
                "FROM Guide " \
                "INNER JOIN Channels ON Channels.GUID = Guide.Channel_GUID ORDER BY Channels.Call_Sign ASC"
        try:
            cursor = self.DB.cursor()
            cursor.execute(query)
            schedule = cursor.fetchall()
            if schedule is not None and len(schedule):
                i = 0
                progress = xbmcgui.DialogProgressBG()
                progress.create('Sling TV')
                progress.update(i, 'Building EPG XML...')
            for row in schedule:
                i += 1
                percent = int((float(i) / len(schedule)) * 100)
                progress.update(percent)
                start_time = str(row[0])
                stop_time = str(row[1])
                channel_id = str(row[2])
                title = strip(row[3]).replace("''", "'")
                sub_title = strip(row[4]).replace("''", "'")
                desc = strip(row[5]).replace("''", "'")
                icon = str(row[6])
                genres = row[7]
                genres = genres.split(',')

                prg = ''
                prg += '<programme start="%s" stop="%s" channel="%s">\n' % (start_time, stop_time, channel_id)
                prg += '    <title lang="en">%s</title>\n' % title
                prg += '    <sub-title lang="en">%s</sub-title>\n' % sub_title
                prg += '    <desc lang="en">%s</desc>\n' % desc
                for genre in genres:
                    prg += '    <category lang="en">%s</category>\n' % str(genre).strip().capitalize()
                prg += '    <icon src="%s"/>\n' % icon
                prg += '</programme>\n'

                master_file.write(str(prg))
                if self.Monitor.abortRequested():
                    break
            progress.close()

        except sqlite3.Error as err:
            log('buildEPG(): Failed to retrieve guide data from DB, error => %s\rQuery => %s' % (err, query))
        except Exception as exc:
            log('buildEPG(): Failed to retrieve retrieve guide data from DB, exception => %s\rQuery => %s' % (exc, query))

        master_file.write('</tv>')
        master_file.close()

    def checkIPTV(self):
        log('Slinger function: checkIPTV()')
        if xbmc.getCondVisibility('System.HasAddon(pvr.iptvsimple)'):
            iptv_settings = [['epgPathType', '0'],
                             ['epgTSOverride', 'true'],
                             ['epgPath', self.EPG_Path],
                             ['m3uPathType', '0'],
                             ['m3uPath', self.Playlist_Path],
                             ['logoFromEpg', '1'],
                             ['logoPathType', '1']
                             ]
            for id, value in iptv_settings:
                if xbmcaddon.Addon('pvr.iptvsimple').getSetting(id) != value:
                    xbmcaddon.Addon('pvr.iptvsimple').setSetting(id=id, value=value)

    def toggleIPTV(self):
        log('Slinger function: toggleIPTV()')
        if not xbmc.getCondVisibility('System.HasAddon(pvr.iptvsimple)'):
            dialog = xbmcgui.Dialog()
            dialog.notification('Sling', 'Please enable PVR IPTV Simple Client', xbmcgui.NOTIFICATION_INFO, 5000, False)
        else:
            pvr_toggle_off = '{"jsonrpc": "2.0", "method": "Addons.SetAddonEnabled", "params": ' \
                             '{"addonid": "pvr.iptvsimple", "enabled": false}, "id": 1}'
            pvr_toggle_on = '{"jsonrpc": "2.0", "method": "Addons.SetAddonEnabled", "params": ' \
                            '{"addonid": "pvr.iptvsimple", "enabled": true}, "id": 1}'
            xbmc.executeJSONRPC(pvr_toggle_off)
            xbmc.executeJSONRPC(pvr_toggle_on)

    def updateShows(self):
        log('Slinger function: updateShows()')
        query = "SELECT * FROM Shows ORDER BY Name ASC"
        try:
            cursor = self.DB.cursor()
            cursor.execute(query)
            shows = cursor.fetchall()
            if shows is not None and len(shows):
                progress = xbmcgui.DialogProgressBG()
                progress.create('Sling TV')
                progress.update(0, 'Updating Shows...' )
                show_count = 0
                for show in shows:
                    show_guid = show[0]
                    db_show = Show(show_guid, self.EndPoints, self.DB, silent=True)
                    if db_show.GUID != '':
                        db_show.getSeasons(update=True, silent=True)
                    show_count += 1
                    progress.update(int((float(show_count) / len(shows)) * 100))
                    if self.Monitor.abortRequested():
                        break
                progress.close()
            result = True
        except sqlite3.Error as err:
            log('updateShows(): Failed to retrieve shows from DB, error => %s' % err)
            result = False
        except Exception as exc:
            log('updateShows(): Failed to retrieve shows from DB, exception => %s' % exc)
            result = False
        return result

    def updateOnDemand(self):
        log('Slinger function: updateOnDemand()')
        timestamp = int(time.time())
        query = "SELECT GUID FROM Channels WHERE On_Demand = 1"
        try:
            cursor = self.DB.cursor()
            cursor.execute(query)
            channels = cursor.fetchall()
            if channels is not None and len(channels):
                progress = xbmcgui.DialogProgressBG()
                progress.create('Sling TV')
                progress.update(0, 'Updating On Demand...' )
                channel_count = 0
                for channel in channels:
                    channel_guid = channel[0]
                    db_channel = Channel(channel_guid, self.EndPoints, self.DB)
                    if db_channel.GUID != '':
                        categories = db_channel.getOnDemandCategories()
                        for category in categories:
                            db_channel.getOnDemandAssets(category['Name'], update=True)
                            if self.Monitor.abortRequested():
                                break
                    channel_count += 1
                    progress.update(int((float(channel_count) / len(channels)) * 100))
                    if self.Monitor.abortRequested():
                        break

                query = "DELETE FROM On_Demand_Folders WHERE Expiration < %i" % timestamp
                cursor.execute(query)
                self.DB.commit()
                progress.close()
            result = True
        except sqlite3.Error as err:
            log('updateShows(): Failed to retrieve On Demand Channels from DB, error => %s' % err)
            result = False
        except Exception as exc:
            log('updateShows(): Failed to retrieve On Demand Channels from DB, exception => %s' % exc)
            result = False
        return result


    def updateVOD(self):
        log('Slinger function: updateVOD()')
        timestamp = int(time.time())

        query = "DELETE FROM VOD_Assets WHERE Stop < %i" % timestamp
        try:
            cursor = self.DB.cursor()
            cursor.execute(query)
            self.DB.commit()
            result = True
        except sqlite3.Error as err:
            log('updateShows(): Failed to clean up VOD from DB, error => %s' % err)
            result = False
        except Exception as exc:
            log('updateShows(): Failed to clean up VOD from DB, exception => %s' % exc)
            result = False
        return result

    def createDB(self):
        log('Slinger function: createDB()')
        sql_file = xbmcvfs.File(SQL_PATH)
        sql = sql_file.read()
        sql_file.close()

        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        if sql != "":
            try:
                cursor.executescript(sql)
                db.commit()
            except sqlite3.Error as err:
                log('createDB(): Failed to create DB tables, error => %s' % err)
            except Exception as exc:
                log('createDB(): Failed to create DB tables, exception => %s' % exc)
        db.close()

    def buildEndPoints(self):
        log('Slinger function: buildEndPoints()\r%s' % WEB_ENDPOINTS)
        endpoints = {}
        response = requests.get(WEB_ENDPOINTS, headers=HEADERS, verify=VERIFY)
        if response is not None and response.status_code == 200:
            endpoints = response.json()['environments']['production']

        return endpoints

    def close(self):
        log('Slinger function: close()')
        self.DB.close()
        del self.Monitor