"""Execute the actual display helpers; never decode provider replay in JS."""
import json
import subprocess

from tests.test_issue2613_render_cache_signature import NODE, _collect_functions


def run_node(names, body):
    result = subprocess.run([NODE, '-e', 'const window={};\n'+_collect_functions(names)+'\n'+body],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_projection_changes_invalidate_cached_history():
    result=run_node(['_messageRenderCacheSignature','_addBoundedHash','_hashObjectInto','msgContent','_messageHasReasoningPayload'], '''
        const S={messages:[{role:'assistant',content:'Done.'}],toolCalls:[]};
        const base=_messageRenderCacheSignature();
        S.messages[0].display_commentary=['Checking.'];
        const withProse=_messageRenderCacheSignature();
        S.messages[0].display_commentary=[];
        const disabled=_messageRenderCacheSignature();
        S.messages[0].display_reasoning='Separate thought';
        console.log(JSON.stringify([base,withProse,disabled,_messageRenderCacheSignature()]));
    ''')
    assert result[0] != result[1]
    assert result[1] != result[2]
    assert result[2] != result[3]


def test_only_projected_assistant_commentary_is_eligible():
    assert run_node(['_assistantDisplayCommentary'], '''
        console.log(JSON.stringify([
          _assistantDisplayCommentary({role:'assistant',display_commentary:['One.',null,{},'', 'Two.']}),
          _assistantDisplayCommentary({role:'assistant',codex_message_items:[{phase:'commentary',text:'Raw replay'}]}),
          _assistantDisplayCommentary({role:'assistant',display_kind:'hidden',display_commentary:['Hidden.']}),
          _assistantDisplayCommentary({role:'tool',display_commentary:['Not assistant.']})
        ]));
    ''') == [['One.', 'Two.'], [], [], []]


def test_scene_recovery_preserves_equal_commentary_owners():
    result=run_node(['_assistantDisplayCommentary','_compactSceneRowsWithPersistedUpdates','_anchorSceneProseMatchesFinalAnswer','_anchorSceneRowTimestampSeconds'], r"""
        const S={messages:[{role:'assistant',content:'',timestamp:2,display_commentary:['Checking.']},
                          {role:'assistant',content:'',timestamp:4,display_commentary:['Checking.']}]};
        const _messageSessionIndexForRawIdx=i=>90+i;
        const _isAssistantEmptyPlaceholderContent=()=>false;
        const blocks={querySelectorAll:()=>[0,1].map(i=>({dataset:{msgIdx:String(i)},getAttribute:()=>''}))};
        const live=[{role:'prose',row_id:'live',text:'Checking.',timestamp:2}];
        const rows=_compactSceneRowsWithPersistedUpdates(live,blocks,2);
        console.log(JSON.stringify(rows.filter(r=>r.role==='prose').map(r=>[r.text,r.group?.assistant_msg_idx])));
    """)
    assert result==[['Checking.',90],['Checking.',91]]



def test_final_commentary_echo_stays_outside_processed():
    assert run_node(['_assistantDisplayCommentary','_compactSceneRowsWithPersistedUpdates','_anchorSceneProseMatchesFinalAnswer','_anchorSceneRowTimestampSeconds'], r"""
        const S={messages:[{role:'assistant',content:'Done.',display_commentary:['Done.']}]};
        const _isAssistantEmptyPlaceholderContent=()=>false;
        const blocks={querySelectorAll:()=>[{dataset:{msgIdx:'0'},getAttribute:()=> 'Done.'}]};
        console.log(JSON.stringify(_compactSceneRowsWithPersistedUpdates([],blocks,0)));
    """)==[]


def test_empty_reasoning_projection_preserves_other_carriers():
    assert run_node(['_assistantReasoningPayloadText'], r"""
        console.log(JSON.stringify([
            _assistantReasoningPayloadText({role:'assistant',display_reasoning:'',thinking:'Other thought.'}),
            _assistantReasoningPayloadText({role:'assistant',display_reasoning:'',reasoning:'Public commentary.'}),
            _assistantReasoningPayloadText({role:'assistant',display_reasoning:'',content:[{type:'thinking',text:'Content thought.'}]})
        ]));
    """)==['Other thought.','','Content thought.']
