from nameko.web.handlers import http
from nameko.rpc import rpc, RpcProxy
from nameko.events import event_handler, EventDispatcher
from nameko_mongodb import MongoDatabase
from werkzeug.wrappers import Request, Response
import json


class UIS:
    # Vars

    name = 'uis'

    db = MongoDatabase()
    '''
        name of collection: 'interests';
        columns:
                '_id' - id of the user
                'tags' - the dict:
                    {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}
                        where `w_i` is a weight of the tag named 'tag_name_i'
                'count_changes' -\
                    - how many changes of weights the user in effect had done
                'q_tags' - tags of current questionnaire
        
        name of collection: 'bool_interests';
        columns:
            '_id' - id of the user
            'bool_list' - the list of True, False
    '''

    dispatch = EventDispatcher()
    '''
        calling for service 'ranking' if change of weights had done
    '''

    event_das_rpc = RpcProxy('event_das')
    '''
        in order to get tags of event
    '''
    logger_rpc = RpcProxy('logger')
    '''
        used to track logs
    '''
    l_weight = 1.0  # the weight of a like
    f_weight = 5.0  # assume that one fav is equal to 5 likes of events with the same tags
    q_weight = 50.0  # and one questionnaire is equal to 50 likes

    # Logic

    def _add_questionnaire_data(self, new_q):
        '''
            Args: new_q - [user_id, [tag_1, tag_2, ..., tag_m]] -\
                a questionnaire of the user
            Returns: [user_id, {tag_1: w_1, tag_2: w_2, ..., tag_n: w_n}] -\
                - all user's tags with their weights
        '''

        user_id, new_tags_list = new_q
        collection = self.db['interests']

        previous_questionnaire_tags = collection.find_one(
            {'_id': user_id},
            {'q_tags': 1}
        )

        if previous_questionnaire_tags:
            '''
                that is not the first questionnaire, 
                which means we should get rid of old data 
                and replace it with the new one
            '''
            previous_questionnaire_tags = previous_questionnaire_tags['q_tags']

            tags = collection.find_one(
                {'_id': user_id},
                {'tags': 1}
            )['tags']

            count = collection.find_one(
                {'_id': user_id},
                {'count_changes': 1}
            )['count_changes']
            '''count_changes var is not gonna be incremented 
            because we simply replace one questionnaire with another one'''

            # getting rid of influence of previous questionnaire
            for old_tag in previous_questionnaire_tags:
                tags[old_tag] -= self.q_weight/count
                if tags[old_tag] < 0:  # actually that gonna be only in case of a deviation
                    tags[old_tag] = 0.0

            # add weights from new questionnaire
            for new_tag in new_tags_list:
                if new_tag in tags:
                    # that tag is already presented
                    total_weight = tags[new_tag]
                else:
                    # this is the new tag
                    total_weight = 0.0
                tags[new_tag] = total_weight + self.q_weight/count

            collection.update_one(
                {'_id': user_id},
                {'$set': {'tags': tags,
                          'q_tags': new_tags_list}}
            )
            return [user_id, tags]
        else:
            '''
                that is the first questionnaire
            '''
            new_tags_dict = {}  # questionnaire tags with their weights
            for tag in new_tags_list:
                new_tags_dict[tag] = 1.0

            collection.insert_one(
                {'_id': user_id, 'tags': new_tags_dict,
                    'count_changes': self.q_weight, 'q_tags': new_tags_list}
            )
            return [user_id, new_tags_dict]

    def _update_reaction_data(self, user_id, event_tags, w, cancel=False):
        '''
        Args: 
            user_id - id of the user
            event_tags - [event_1_tag, ..., event_n_tag] - \
                - list of tags related to event that we have reaction on
            w - float; means weight of the reaction
            cancel - bool; True if we get reaction back, False otherwise
        Returns:
            [user_id, {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}]
            user_id and user's tags with their weights
            or None if user is not presented in database
        logic:
            changes weights in according with the principle:
                the weight of the tag equals to probability of the fact that
                that tag is presented in a random chosen event that the user has highlighted
            for that:
            assume that all tags are of the same authority and use pattern:
                total_weight = (total_weight*count +|- \
                                new_weight_of_this_tag)/(count +|- w)
                count +|- w
            where `w` is weight of the reaction
            and +|- depends on adding or cancelling reaction
        '''

        collection = self.db['interests']

        is_user_presented = collection.find_one(
            {'_id': user_id}
        )
        if not is_user_presented:
            print('that user cannot make or cancel reactions')
            return None

        user_tags = collection.find_one(
            {'_id': user_id},
            {'tags': 1}
        )['tags']
        count = collection.find_one(
            {'_id': user_id},
            {'count_changes': 1}
        )['count_changes']

        if cancel:
            '''
            getting reaction back
            '''
            for event_tag in event_tags:
                try:
                    user_tags[event_tag] = (
                        user_tags[event_tag]*count - w)/(count-w)
                except Exception:
                    print(Exception,
                          '!we don\'t have the possibility to cancel reaction!')
                    user_tags[event_tag] = 0.0

            for user_tag in user_tags:
                if user_tag not in event_tags:
                    user_tags[user_tag] = user_tags[user_tag]*count/(count-w)

            collection.update_one(
                {'_id': user_id},
                {'$set': {'count_changes': count-w, 'tags': user_tags}}
            )
        else:
            '''
            adding reaction
            '''
            for event_tag in event_tags:
                if event_tag in user_tags:
                    total_weight = user_tags[event_tag]
                else:
                    total_weight = 0.0
                user_tags[event_tag] = (total_weight*count + w)/(count+w)

            for user_tag in user_tags:
                if user_tag not in event_tags:
                    user_tags[user_tag] = user_tags[user_tag]*count/(count+w)

            collection.update_one(
                {'_id': user_id},
                {'$set': {'count_changes': count+w, 'tags': user_tags}}
            )

        return [user_id, user_tags]

    def _get_weights_by_id(self, user_id):
        '''
            Args: user_id - id of the user
            Returns: 
                None if that user is not presented in database
                {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n} - \
                    - user's tags with their weights otherwise
        '''
        collection = self.db['interests']

        user_weights = collection.find_one(
            {'_id': user_id},
            {'tags': 1}
        )

        if user_weights:
            return user_weights['tags']
        else:
            return None

    def _bool_list_action(self, user_id, is_get, bool_list=[]):
        '''
        Args:
            user_id - id of the user
            is_get - bool - True if the func called to get list, False to save list
            bool_list the list lke [True, False, False, ...]
        Returns: 
            if is_get - current bool_list or None if user is not presented
            else nothing
        '''

        collection = self.db['bool_interests']
        is_user = collection.find_one(
            {'_id': user_id},
            {'bool_list': 1}
        )

        if is_get:
            if is_user:
                return is_user['bool_list']
            return None

        if is_user:
            collection.update_one(
                {'_id': user_id},
                {'$set': {'bool_list': bool_list}}
            )
        else:
            collection.insert_one(
                {'_id': user_id, 'bool_list': bool_list}
            )

    # API

    # rpc

    @rpc
    def create_new_q(self, questionnaire):
        '''
            Args: questionnaire - [user_id, [tag_1, tag_2, ..., tag_m]] -\
                a questionnaire of the user
            Dispatch to the ranking: 
                [user_id, {tag_1: w_1, tag_2: w_2, ..., tag_n: w_n}] -\
                    - all user's tags with their weights
        '''
        self.logger_rpc.log(self.name, self.create_new_q.__name__,
                            questionnaire, "Info", "Creating questionnaire")

        data = self._add_questionnaire_data(questionnaire)
        self.dispatch('make_top', data)

    @rpc
    # 'likes' is the name of listened service, 'like' is the message
    @event_handler('likes', 'like')
    def add_like(self, like_data):
        '''
            like
            Args: like_data - [user_id, event_id]
            Dispatch to the ranking: 
                [user_id, {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}] -\
                    user_id and user's tags with their weights.
        '''
        self.logger_rpc.log(self.name, self.add_like.__name__,
                            like_data, "Info", "Saving like")

        # get event's tags
        event_tags = self.event_das_rpc.get_tags_by_id(like_data[1])

        data = self._update_reaction_data(
            like_data[0], event_tags, self.l_weight)
        self.dispatch('make_top', data)

    @rpc
    # 'likes' is the name of listened service, 'like_cancel' is the message
    @event_handler('likes', 'like_cancel')
    def cancel_like(self, like_data):
        '''
            cancel like
            Args: like_data - [user_id, event_id]
            Dispatch to the ranking: 
                [user_id, {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}] -\
                    user_id and user's tags with their weights.
        '''
        self.logger_rpc.log(self.name, self.cancel_like.__name__,
                            like_data, "Info", "Cancelling like")

        # get event's tags
        event_tags = self.event_das_rpc.get_tags_by_id(like_data[1])

        data = self._update_reaction_data(
            like_data[0], event_tags, self.l_weight, True)
        # True means we get reaction back
        self.dispatch('make_top', data)

    @rpc
    # 'favorites' is the name of listened service, 'fav' is the message
    @event_handler('favorites', 'fav')
    def add_fav(self, fav_data):
        '''
            add to favorites
            Args: fav_data - [user_id, event_id]
            Dispatch to the ranking: 
                [user_id, {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}] -\
                    user_id and user's tags with their weights.
        '''
        self.logger_rpc.log(self.name, self.add_fav.__name__,
                            fav_data, "Info", "Add to favorite")

        # get event's tags
        event_tags = self.event_das_rpc.get_tags_by_id(fav_data[1])

        data = self._update_reaction_data(
            fav_data[0], event_tags, self.f_weight)
        self.dispatch('make_top', data)

    @rpc
    # 'favorites' is the name of listened service, 'fav_cancel' is the message
    @event_handler('favorites', 'fav_cancel')
    def cancel_fav(self, fav_data):
        '''
            remove from favorites
            Args: fav_data - [user_id, event_id]
            Dispatch to the ranking: 
                [user_id, {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n}] -\
                    user_id and user's tags with their weights.
        '''
        self.logger_rpc.log(self.name, self.cancel_fav.__name__,
                            fav_data, "Info", "Cancelling favorite")

        # get event's tags
        event_tags = self.event_das_rpc.get_tags_by_id(fav_data[1])

        data = self._update_reaction_data(
            fav_data[0], event_tags, self.f_weight, True)
        # True means we get reaction back
        self.dispatch('make_top', data)

    @rpc
    def get_weights_by_id(self, user_id):
        '''
            Args: user_id - id of the user
            Returns: 
                None if that user is not presented in database
                {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n} - \
                    - user's tags with their weights otherwise
        '''
        return self._get_weights_by_id(user_id)

    @rpc
    def save_bool_list(self, user_id, bool_list):
        '''
        Args:
            user_id - id of the user
            bool_list - [True, False, False, ...]
        Returns: nothing
        '''
        self._bool_list_action(user_id, False, bool_list)

    @rpc
    def get_bool_list(self, user_id):
        '''
        Args:
            user_id - id of the user
        Returns: bool list if user is presented in db, None otherwise
        '''
        return(self._bool_list_action(user_id, True))

    # http

    @http('POST', '/newq')
    def create_new_q_http(self, request: Request):
        '''
            POST http://localhost:8000/newq HTTP/1.1
            Content-Type: application/json
            [user_id, [
                'tag_1', 'tag_2', ..., 'tag_m'
            ]]
        '''
        content = request.get_data(as_text=True)
        questionnaire = json.loads(content)
        data = self._add_questionnaire_data(questionnaire)
        self.dispatch('make_top', data)
        return Response(status=201)

    @http('POST', '/got_like')
    def add_like_http(self, request: Request):
        '''
            POST http://localhost:8000/got_like HTTP/1.1
            Content-Type: application/json
            [user_id, event_id]
        '''
        content = request.get_data(as_text=True)
        like_message = json.loads(content)

        event_tags = self.event_das_rpc.get_tags_by_id(like_message[1])

        data = self._update_reaction_data(
            like_message, event_tags, self.l_weight)
        self.dispatch('make_top', data)

        return Response(status=201)

    @http('POST', '/cancel_like')
    def cancel_like_http(self, request: Request):
        '''
            POST http://localhost:8000/cancel_like HTTP/1.1
            Content-Type: application/json
            [user_id, event_id]
        '''
        content = request.get_data(as_text=True)
        like_message = json.loads(content)

        event_tags = self.event_das_rpc.get_tags_by_id(like_message[1])

        data = self._update_reaction_data(
            like_message, event_tags, self.l_weight, True)
        self.dispatch('make_top', data)

        return Response(status=201)

    @http('POST', '/got_fav')
    def add_fav_http(self, request: Request):
        '''
            POST http://localhost:8000/got_fav HTTP/1.1
            Content-Type: application/json
            [user_id, event_id]
        '''
        content = request.get_data(as_text=True)
        fav_message = json.loads(content)

        event_tags = self.event_das_rpc.get_tags_by_id(fav_message[1])

        data = self._update_reaction_data(
            fav_message, event_tags, self.f_weight)
        self.dispatch('make_top', data)

        return Response(status=201)

    @http('POST', '/cancel_fav')
    def cancel_fav_http(self, request: Request):
        '''
            POST http://localhost:8000/cancel_fav HTTP/1.1
            Content-Type: application/json
            [user_id, event_id]
        '''
        content = request.get_data(as_text=True)
        fav_message = json.loads(content)

        event_tags = self.event_das_rpc.get_tags_by_id(fav_message[1])

        data = self._update_reaction_data(
            fav_message, event_tags, self.f_weight, True)
        self.dispatch('make_top', data)

        return Response(status=201)

    @http('GET', '/get_weights/<id>')
    def get_weights_by_id_http(self, request: Request, user_id):
        '''
            Args: user_id - id of the user
            Returns: 
                None if that user is not presented in database
                {'<tag_name_1>': w_1, ..., '<tag_name_n>': w_n} - \
                    - user's tags with their weights otherwise
        '''
        user_weights = self._get_weights_by_id(user_id)
        return json.dumps(user_weights, ensure_ascii=False)
