# Copyright (c) 2006-2007, H. Andres Lagar-Cavilla, University of Toronto
# In the context of the vmgl project
#
# See the file LICENSE.txt for information on redistributing this software.

import sys

sys.path.append( "../glapi_parser" )
import apiutil

apiutil.CopyrightC()
print """
/* Copyright (c) 2006-2007, H. Andres Lagar-Cavilla, University of Toronto.
 * In the context of the vmgl project. */

#include <stdio.h>
#include "cr_server.h"
#include "cr_packfunctions.h"
#include "packspu.h"
#include "packspu_proto.h"

/* DO NOT EDIT.  This code is generated by packspu_resume_autogen.py. */
"""

keys = apiutil.GetDispatchedFunctions("../glapi_parser/APIspec.txt")

## This will generate a heap of new code. What we basically will do is 
## annotate everything with the appropriate DLM calls. If necessary we 
## will also keep track of state, to later diff and obtain it during
## OpengGL state resume. Depending on the function properties we will
## pack and ship, and writebak and obtain return vals.

for func_name in keys:
	# Precomp some useful tidbits
	return_type = apiutil.ReturnType(func_name)
	chromiumProps = apiutil.ChromiumProps(func_name)
	params = apiutil.Parameters(func_name)

	# Skip this function if we have a specialized implementation
	if apiutil.FindSpecial("packspu", func_name) or apiutil.FindSpecial("packspu_vertex", func_name):
		continue
		
	if "get" in apiutil.Properties(func_name):
		continue        
	
	# Ok, need to find out more about this function. Apiutil to our rescue

	# Initialize
	functionCouldDL = 0
	functionUsesClientState = 0
	functionTracksState = 0
	functionPacks = apiutil.CanPack(func_name)
	functionFlushes = 0
	functionReadsBack = 0
	functionParamsString = apiutil.MakeCallString(params)
	packerParamsString = functionParamsString
	dlmParamsString = functionParamsString

	# If you can be compiled in a display list we'll have to check with DLM
	if apiutil.CanCompile(func_name):
		functionCouldDL = 1

	# packspu_flush_special (barriers, semaphores) need to go right away
	if apiutil.FindSpecial("packspu_flush", func_name):
		functionFlushes = 1

	# serverdependent functions are packed, sent immediately,
	# and a response is read
	if "serverdependent" in chromiumProps:
		functionPacks = 1
		functionFlushes = 1
		functionReadsBack = 1
		if return_type == 'void':
			packerParamsString = packerParamsString + ', &writeback'
		else:
			packerParamsString = packerParamsString + ', &return_val, &writeback'

	# If you use client state we might need to change packer and DLM invokation strings
	if apiutil.UsesClientState(func_name):
		if functionPacks:
			functionUsesClientState = 1
			packerParamsString = functionParamsString + ", &(clientState->unpack)"
		if functionCouldDL:
			functionUsesClientState = 1
			dlmParamsString = functionParamsString + ", clientState"

	# glMaterial* calls annoying
	if func_name[0:8] == "Material":
		functionTracksState = 1
	
	# If you set tracked state we'll (obviously) call the state tracker.
	# Client side state changes stay here
	if apiutil.SetsTrackedState(func_name):
		functionTracksState = 1
		if apiutil.SetsClientState(func_name):
			functionPacks = 0

	# At this point we now the needs of this call in terms of state
	# setting, DLM, packing, flushingm and return values. If you don't 
	# need anything, bye bye.
	# Otherwise skip this function.
	if not functionCouldDL and not functionUsesClientState and not functionFlushes and not functionTracksState and not functionReadsBack and functionPacks:
		continue

	# Function header
	print '%s PACKSPU_APIENTRY packspu_%s( %s )' % ( return_type, func_name, apiutil.MakeDeclarationString( params ) )
	print '{'
	# Silence compiler warnings
	if not ((func_name == "DeleteFencesNV") or (func_name == "DeleteTextures") or (func_name == "DisableVertexAttribArrayARB") or
	(func_name == "EnableVertexAttribArrayARB") or (func_name == "FeedbackBuffer") or (func_name == "FlushVertexArrayRangeNV") or
	(func_name == "IndexPointer") or (func_name == "PixelStorei") or (func_name == "PixelStoref") or (func_name == "VertexArrayRangeNV")):
		print '\tGET_THREAD(thread);'

	# Following set of if's do the obvious
	# First, parameters
	if functionUsesClientState:
		## Grr, can't call GET_CONTEXT, duplicate 'tard code
		print "\tContextInfo *ctx = thread->currentContext;"
		print "\tCRClientState *clientState = &(ctx->clientState->client);";

	if functionReadsBack:
		print '\tint writeback = 1;'
		if return_type != 'void':
			print '\t%s return_val = (%s) 0;' % (return_type, return_type)

	# If this element can be compiled into a display list, we have
	# to check to see if it should be compiled first.  For most
	# functions, the 'functionCouldDL' check is sufficient; but some functions
	# need to invoke the crDLMCheckLists call, to find out if it
	# should be executed immediately.
	if functionCouldDL:
		if "checklist" in chromiumProps:
			print '\tif ( IN_DL(thread) && crDLMCheckList%s(%s) )' % (func_name, functionParamsString)
		else:
			print '\tif (IN_DL(thread))'
		print '\t\tcrDLMCompile%s(%s);' % (func_name, dlmParamsString)

	# Ok, we send it through the net if need be
	if functionPacks:
		print '\tif (pack_spu.swap)'
		print '\t{'
		print '\t\tcrPack%sSWAP(%s);' % (func_name, packerParamsString)
		print '\t}'
		print '\telse'
		print '\t{'
		print '\t\tcrPack%s(%s);' % (func_name, packerParamsString)
		print '\t}'
	
	# And this final set of if's do the necessary "post-send" adjustments
	if functionFlushes:
		print '\tpackspuFlush(thread);'

	if functionTracksState:
		# State-tracking only if the function warrants and outside display list compilation
		if functionCouldDL:
			print '\tif (NOT_COMPILE_DL(thread))'
			print '\t\tcrState%s( %s );' % (func_name, functionParamsString)	
		elif return_type == 'void':
			print '\tcrState%s( %s );' % ( func_name, functionParamsString)
		else:
			print '\treturn crState%s( %s );' % ( func_name, functionParamsString)

	if functionReadsBack:
		print '\twhile (writeback)'
		print '\t\tcrNetRecv();'
		if return_type != 'void':
			print '\tif (pack_spu.swap)'
			print '\t{'
			print '\t\treturn_val = (%s) SWAP32(return_val);' % return_type
			print '\t}'
			print '\treturn return_val;'

	# Close function body.
	print '}'
	print ''

