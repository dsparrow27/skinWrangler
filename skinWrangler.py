"""
skinWrangler
Christopher Evans, Version 2.0, July 2014
@author = Chris Evans
version = 2.0

TODO
- if a joint is selected and zeroed out, don't keep it selected on refresh and focus on it
- throw warning if every inf in the active list is selected to be zeroed out
- figure out a way to color mesh from joint influence colors
- better skin mirror with friggin feedback as to what points aren't found

Add this to a shelf:
import skinWrangler as sw
skinWranglerWindow = sw.show()

"""

import os
import logging

from qt import QtWidgets, QtGui, QtCore

try:
    from shiboken2 import wrapInstance
except ImportError:
    import shiboken

import maya.cmds as cmds
import maya.mel as mel
from maya.api import OpenMaya as om2
from maya.OpenMayaUI import MQtUtil

import skinwranglersource

logger = logging.getLogger(__name__)


def _initSkinWrangler():
    """internal Function that get's called by maya's workspace control to actually create the GUI.
    """
    ptr = MQtUtil.getCurrentParent()
    workspace_control = wrapInstance(long(ptr), QtWidgets.QWidget)
    skinWranglerWindow = SkinWrangler(parent=workspace_control)
    skinWranglerWindow.show()
    return skinWranglerWindow


def show():
    global skinWranglerWindow
    try:
        skinWranglerWindow.close()
    except:
        pass

    if cmds.workspaceControl(SkinWrangler.title, exists=True):
        cmds.workspaceControl(SkinWrangler.title, remove=True)
    # have to use workspace control and must pass a string to create any ui(thanks autodesk...not!!!)
    # also r=True == raise but raise is python reserved word, lets use the shortName
    cmds.workspaceControl(SkinWrangler.title, retain=False,
                          floating=True, r=True, uiScript="skinWrangler._initSkin()")


########################################################################
## SKIN WRANGLER
########################################################################

class SkinWrangler(QtWidgets.QDialog):
    title = 'skinWrangler 2.0'

    currentMesh = None
    currentSkin = None
    currentInf = None
    currentVerts = None
    currentNormalization = None

    scriptJobNum = None
    copyCache = None

    jointLoc = None

    iconLib = {}
    iconPath = os.path.join(os.environ.get('MAYA_LOCATION', ""), "icons")
    iconLib['joint'] = QtGui.QIcon(QtGui.QPixmap(os.path.join(iconPath, 'kinJoint.png')))
    iconLib['ikHandle'] = QtGui.QIcon(QtGui.QPixmap(os.path.join(iconPath, 'kinHandle.png')))
    iconLib['transform'] = QtGui.QIcon(QtGui.QPixmap(os.path.join(iconPath, 'orientJoint.png')))

    def __init__(self, parent=None):
        super(SkinWrangler, self).__init__(parent=parent)
        self.resize(348, 732)
        self.setWindowFlags(QtCore.Qt.MSWindowsFixedSizeDialogHint)
        self.ui = skinwranglersource.Ui_skinWranglerDlg()
        self.ui.setupUi(self)
        self.setWindowTitle(self.title)
        self.setObjectName(self.__class__.__name__)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        ## Connect UI
        ########################################################################
        self.ui.refreshBTN.clicked.connect(self.refreshUI)
        self.ui.selShellBTN.clicked.connect(self.selShellFn)
        self.ui.selGrowBTN.clicked.connect(self.selGrowFn)
        self.ui.selShrinkBTN.clicked.connect(self.selShrinkFn)
        self.ui.selLoopBTN.clicked.connect(self.selLoopFn)
        self.ui.selPointsEffectedBTN.clicked.connect(self.selPointsEffectedFn)
        self.ui.weightZeroBTN.clicked.connect(self.weightZeroFn)
        self.ui.weightHalfBTN.clicked.connect(self.weightHalfFn)
        self.ui.weightFullBTN.clicked.connect(self.weightFullFn)
        self.ui.setWeightBTN.clicked.connect(self.setWeightFn)
        self.ui.plusWeightBTN.clicked.connect(self.plusWeightFn)
        self.ui.minusWeightBTN.clicked.connect(self.minusWeightFn)
        self.ui.copyBTN.clicked.connect(self.copyFn)
        self.ui.pasteBTN.clicked.connect(self.pasteFn)
        self.ui.selectVertsWithInfBTN.clicked.connect(self.selectVertsWithInfFn)
        self.ui.setAverageWeightBTN.clicked.connect(self.setAverageWeightFn)
        self.ui.jointLST.itemSelectionChanged.connect(self.jointListSelChanged)
        self.ui.listAllCHK.stateChanged.connect(self.listAllChanged)
        self.ui.nameSpaceCHK.stateChanged.connect(self.cutNamespace)
        self.ui.skinNormalCMB.currentIndexChanged.connect(self.skinNormalFn)
        self.ui.filterLINE.returnPressed.connect(self.refreshUI)
        self.ui.filterBTN.clicked.connect(self.refreshUI)
        self.ui.clampInfBTN.clicked.connect(self.clampInfFn)
        self.ui.bindPoseBTN.clicked.connect(self.bindPoseFn)
        self.ui.removeUnusedBTN.clicked.connect(self.removeUnusedFn)
        self.ui.addJntBTN.clicked.connect(self.addJntFn)
        self.ui.jointOnBboxCenterBTN.clicked.connect(self.jointOnBboxCenterFn)

        logger.debug('skinWrangler initialized as {}'.format(self.objectName()))
        self.scriptJobNum = cmds.scriptJob(e=['SelectionChanged', self.refreshUI], p=self.objectName(), kws=1)
        self.refreshUI()

    def closeEvent(self, e):
        if self.scriptJobNum:
            logger.debug('[skinWrangler] Killing scriptJob ({})'.format(str(self.scriptJobNum)))
            cmds.scriptJob(kill=self.scriptJobNum, force=1)
            self.scriptJobNum = None
        self.removeAnnotations()

    def averageWeights(self, weights):
        try:
            return sum(weights) / len(weights)
        except ZeroDivisionError:
            return 0.0

    def findRelatedSkinCluster(self, skinObject):
        """Python implementation of MEL command: http://takkun.nyamuuuu.net/blog/archives/592"""

        skinShape = None
        skinShapeWithPath = None
        hiddenShape = None
        hiddenShapeWithPath = None

        cpTest = cmds.ls(skinObject, typ="controlPoint")
        if len(cpTest):
            skinShape = skinObject

        else:
            rels = cmds.listRelatives(skinObject)
            if rels is None:
                return False
            for r in rels:
                cpTest = cmds.ls("|".join([skinObject, r]), typ="controlPoint")
                if len(cpTest) == 0:
                    continue

                io = cmds.getAttr('{}|{}.io'.format(skinObject, r))
                if io:
                    continue

                visible = cmds.getAttr("{}|{}.v".format(skinObject, r))
                if not visible:
                    hiddenShape = r
                    hiddenShapeWithPath = "{}|{}".format(skinObject, r)
                    continue

                skinShape = r
                skinShapeWithPath = "{}|{}".format(skinObject, r)
                break

        if skinShape:
            if len(skinShape) == 0:
                if len(hiddenShape) == 0:
                    return None

                else:
                    skinShape = hiddenShape
                    skinShapeWithPath = hiddenShapeWithPath

        clusters = cmds.ls(typ="skinCluster")
        for c in clusters:
            geom = cmds.skinCluster(c, q=True, g=True)
            for g in geom:
                if g == skinShape or g == skinShapeWithPath:
                    return c

        return None

    # annotation
    def removeAnnotations(self):
        annos = cmds.ls('SKINWRANGLER_ANNO_*')
        if annos:
            cmds.delete(annos)

    def annotateNodes(self, nodes):
        """
        Annotate each node with it's name
        """
        for node in nodes:
            anno = cmds.createNode('annotationShape', n='SKINWRANGLER_ANNO', ss=1)
            cmds.setAttr(anno + '.text', node, type='string')
            annoXform = cmds.listRelatives(anno, parent=1)
            cmds.pointConstraint(node, annoXform)
            cmds.setAttr(anno + '.displayArrow', False)
            cmds.rename(annoXform, 'SKINWRANGLER_ANNO_XFORM')

    ## GET FROM SCENE
    ########################################################################
    def getSelected(self):
        # check to make sure a mesh is selected
        msh = cmds.ls(sl=1, o=1, type='mesh')
        if msh:
            skin = self.findRelatedSkinCluster(msh[0])
            if not skin:
                cmds.warning('Cannot find a skinCluster related to [' + msh + ']')
                return False
            self.currentSkin = skin
            self.currentMesh = msh[0]
            cmds.selectMode(component=1)
            sel = cmds.ls(sl=1, flatten=1)
            if sel:
                msh = msh[0]
                vtx = None
                if sel != msh:
                    if sel:
                        vtx = len(sel)
                    else:
                        vtx = 0
                self.currentVerts = sel

                return sel, msh, vtx, skin
        else:
            logger.info('Please select a mesh.')
            return False

    def getAvgVertWeights(self, sel, skin):
        """
        Returns an averaged weight dictionary
        """
        wDict = {}
        for jnt in cmds.skinCluster(skin, q=1, wi=1):
            amt = cmds.skinPercent(skin, sel, q=1, t=jnt)
            if amt > 0.0: wDict[jnt] = amt
        return wDict

    def vDictToTv(self, wDict):
        re = []
        for inf in wDict.keys():
            re.append((inf, wDict[inf]))
        return re

    def skinNormalFn(self, n):
        if n == 0:
            cmds.setAttr("{0}.normalizeWeights".format(self.currentSkin), n)
            self.currentNormalization = 'None'
        elif n == 1:
            cmds.setAttr("{0}.normalizeWeights".format(self.currentSkin), n)
            self.currentNormalization = 'Interactive'
        elif n == 2:
            cmds.setAttr("{0}.normalizeWeights".format(self.currentSkin), n)
            self.currentNormalization = 'Post'
        self.refreshUI()

    ## POLY SELECTION UI
    ########################################################################
    def selGrowFn(self):
        cmds.GrowPolygonSelectionRegion()

    def selShrinkFn(self):
        cmds.ShrinkPolygonSelectionRegion()

    def selShellFn(self):
        cmds.ConvertSelectionToShell()

    def selLoopFn(self):
        cmds.polySelectSp(loop=1)

    def selPointsEffectedFn(self):
        if self.current is None or self.currentInf is None:
            return
        cmds.skinCluster(self.currentSkin, e=1, selectInfluenceVerts=self.currentInf)

    ## JOINT LIST
    ########################################################################
    # TODO: I believe this callback is getting fired twice per user input
    def jointListSelChanged(self, debug=1):
        # TODO: Need to use/store long paths or API pointers here as extra data on the widgets
        try:
            self.currentWidgets = self.ui.jointLST.selectedItems()
            nodes = [item.text(0) for item in self.currentWidgets]
            if nodes:
                if nodes[0] == 'MAKE A COMPONENT\n SELECTION ON\n SKINNED MESH':
                    self.currentInf = []
                    return None

                self.currentInf = nodes

                if debug:
                    logger.debug(self.currentInf)

                # Annotation
                if self.ui.dynAnnotationCHK.isChecked():
                    self.removeAnnotations()
                    self.annotateNodes(nodes)
                if debug:
                    logger.debug(self.currentInf)

        except Exception as e:
            cmds.error(e)

    def getJointFromList(self, jnt):
        for i in range(0, self.ui.jointLST.topLevelItemCount()):
            item = self.ui.jointLST.topLevelItem(i)
            if item.text(0) == jnt: return item
        return False

    def listAllChanged(self):
        self.refreshUI()

    def cutNamespace(self):
        self.refreshUI()

    ## SKINNING FUNCTIONS
    ########################################################################
    def weightZeroFn(self):
        if self.currentInf:
            for inf in self.currentInf:
                cmds.skinPercent(self.currentSkin, self.currentVerts, tv=[inf, 0.0])
            self.refreshUI()

    def weightHalfFn(self):
        if self.currentInf:
            num = len(self.currentInf)
            if num == 1:
                cmds.skinPercent(self.currentSkin, self.currentVerts, tv=[str(self.currentInf[0]), 0.5])
            elif num == 2:
                cmds.skinPercent(self.currentSkin, self.currentVerts, tv=[str(self.currentInf[0]), 1.0])
                cmds.skinPercent(self.currentSkin, self.currentVerts, tv=[str(self.currentInf[1]), 0.5])
            elif num > 2:
                if self.currentNormalization != 'None':
                    cmds.warning('skinWrangler: Cannot skin more than two influences to 0.5 in a normalization mode')
                    return None
                else:
                    for inf in self.currentInf:
                        cmds.skinPercent(self.currentSkin, self.currentVerts, tv=[inf, 0.5])
            self.refreshUI()

    def weightFullFn(self):
        num = 0
        if self.currentInf:
            num = len(self.currentInf)
        if num == 1:
            cmds.skinPercent(self.currentSkin, self.currentVerts, tv=[self.currentInf[0], 1.0])
        elif num > 1:
            if self.currentNormalization != 'None':
                cmds.warning('skinWrangler: Cannot skin more than two influences to 1.0 in a normalization mode')
                return None
        self.refreshUI()

    def setWeightFn(self):
        if self.currentInf:
            if len(self.currentInf) > 1:
                cmds.warning(
                    'skinWrangler: Set Weight does not work with multi-selection because I am too lazy at the moment to write my own normalization code.')
            else:
                cmds.skinPercent(self.currentSkin, self.currentVerts,
                                 tv=[self.currentInf[0], self.ui.setWeightSpin.value()])
            self.refreshUI()
        else:
            cmds.warning('[skinWrangler] No influences/joints selected')

    def plusWeightFn(self):
        try:
            cmds.undoInfo(openChunk=True)
            val = self.ui.setWeightSpin.value()
            if self.currentInf:
                for inf in self.currentInf:
                    cmds.skinPercent(self.currentSkin, self.currentVerts, tv=[inf, val], r=1)
            else:
                cmds.warning('[skinWrangler] No influences/joints selected')
            self.refreshUI()
        except Exception:
            logger.error("Failed to add weight", exc_info=True)
        finally:
            cmds.undoInfo(closeChunk=True)

    def minusWeightFn(self):
        try:
            cmds.undoInfo(openChunk=True)
            val = -self.ui.setWeightSpin.value()
            if self.currentInf:
                for inf in self.currentInf:
                    cmds.skinPercent(self.currentSkin, self.currentVerts, tv=[inf, val], r=1)
            else:
                cmds.warning('[skinWrangler] No influences/joints selected')
            self.refreshUI()
        except Exception:
            logger.error("Failed to minus weight", exc_info=True)
        finally:
            cmds.undoInfo(closeChunk=True)

    def copyFn(self):
        if self.ui.copyBTN.isChecked():
            self.ui.copyBTN.setText('WEIGHTS COPIED')
            self.ui.copyBTN.setStyleSheet("background-color: #7a4242")
            self.getSelected()
            self.copyCache = self.getAvgVertWeights(self.currentVerts, self.currentSkin)
            toolTip = ''
            for item in self.copyCache.keys():
                toolTip += (item + ' - ' + str("%.4f" % self.copyCache[item]) + '\n')
            self.ui.copyBTN.setToolTip(toolTip)
        else:
            self.ui.copyBTN.setText('COPY')
            self.ui.copyBTN.setStyleSheet("background-color: #666666")
            self.ui.copyBTN.setToolTip('')
            self.copyCache = None

    def pasteFn(self):

        if not self.getSelected():
            om2.MGlobal.displayError("No mesh selected, please select a mesh")
            return
        tvTuples = self.vDictToTv(self.copyCache)
        logger.debug('[skinWrangler] Pasting weights to current selection: {}'.format(tvTuples))
        cmds.skinPercent(self.currentSkin, self.currentVerts, tv=tvTuples)
        self.refreshUI()

    def selectVertsWithInfFn(self):
        self.checkMaxSkinInfluences(self.currentMesh, self.ui.selectVertsWithInfSPIN.value(), select=1)

    def setAverageWeightFn(self):
        try:
            cmds.undoInfo(openChunk=True)
            if not self.ui.avgOptionCHK.isChecked():
                mel.eval('weightHammerVerts;')
            else:
                sel = cmds.ls(sl=1)
                cmds.ConvertSelectionToVertices()
                newSel = cmds.ls(sl=1, flatten=1)
                for vert in newSel:
                    self.setAverageWeight(vert)
                self.clampInfluences(self.currentMesh, self.ui.clampInfSPIN.value(), force=True)
                cmds.select(sel)
        except Exception as e:
            cmds.error('skinWrangler: ' + str(e))
        finally:
            cmds.undoInfo(closeChunk=True)

    def setAverageWeight(self, vtx):
        msh = vtx.split('.')[0]
        cmds.select(vtx)
        cmds.ConvertSelectionToEdges()
        cmds.ConvertSelectionToVertices()
        neighbors = cmds.ls(sl=1, flatten=1)
        neighbors.pop(neighbors.index(vtx))
        infList = {}
        skin = self.findRelatedSkinCluster(msh)
        for vert in neighbors:
            for jnt in cmds.skinCluster(skin, q=1, wi=1):
                amt = cmds.skinPercent(skin, vert, q=1, t=jnt)
                if amt > 0.0:
                    if jnt in infList:
                        infList[jnt].append(amt)
                    else:
                        infList[str(jnt)] = [amt]
        for inf in infList:
            total = None
            for w in infList[inf]:
                if not total:
                    total = w
                else:
                    total += w
            weight = total / len(infList[inf])
            cmds.skinPercent(self.currentSkin, vtx, tv=[str(inf), weight], nrm=1)

    def checkMaxSkinInfluences(self, node, maxInf, debug=1, select=0):
        """Takes node name string and max influences int.
        From CG talk thread (MEL converted to Python, then added some things)"""

        cmds.select(cl=1)
        skinClust = self.findRelatedSkinCluster(node)
        if skinClust == "":
            cmds.error("checkSkinInfluences: can't find skinCluster connected to '" + node + "'.\n")

        verts = cmds.polyEvaluate(node, v=1)
        returnVerts = []
        for i in range(0, verts):
            inf = cmds.skinPercent(skinClust, (node + ".vtx[" + str(i) + "]"), q=1, v=1)
            activeInf = []
            for j in range(0, len(inf)):
                if inf[j] > 0.0: activeInf.append(inf[j])
            if len(activeInf) > maxInf:
                returnVerts.append(i)

        if select:
            for vert in returnVerts:
                cmds.select((node + '.vtx[' + str(vert) + ']'), add=1)
        if debug:
            msg = """
            checkMaxSkinInfluences>>> Total Verts:{}
            checkMaxSkinInfluences>>> Vertices Over Threshold:{}
            checkMaxSkinInfluences>>> Indices:{}
            """.format(verts, len(returnVerts), str(returnVerts))
            logger.debug(msg)

        return returnVerts

    def checkLockedInfluences(self, skinCluster):
        """
        Check if provided skinCluster has locked influences
        """
        influenceObjects = cmds.skinCluster(skinCluster, q=True, inf=True)
        for currentJoint in influenceObjects:
            if (cmds.skinCluster(skinCluster, q=True, lw=True, inf=currentJoint)):
                return True
        return False

    def clampInfFn(self):
        self.clampInfluences(self.currentMesh, self.clampInfSPIN.value(), force=True)

    def bindPoseFn(self):
        if self.currentSkin:
            bp = cmds.listConnections(".".join([self.currentSkin, "bindPose"]), s=1)
            if len(bp) > 0:
                cmds.dagPose(bp[0], r=1)
            else:
                cmds.warning('Multiple bind poses detected: ' + str(bp))
        else:
            cmds.warning('No skin cluster loaded or mesh with skin cluster selected.')

    def removeUnusedFn(self):
        if self.currentSkin:
            cmds.skinCluster(self.currentMesh, removeUnusedInfluence=1)
            self.refreshUI()
        else:
            cmds.warning('No skin cluster loaded or mesh with skin cluster selected.')

    def clampInfluences(self, mesh, maxInf, debug=0, force=False):
        """
        Sets max influences on skincluster of mesh / cutting off smallest ones
        """
        skinClust = self.findRelatedSkinCluster(mesh)

        lockedInfluences = self.checkLockedInfluences(skinClust)
        doit = True
        if lockedInfluences:
            if force:
                self.unlockLockedInfluences(skinClust)
                cmds.warning('Locked influences were unlocked on skinCluster')
            else:
                doit = False

        if doit:
            verts = self.checkMaxSkinInfluences(mesh, maxInf)

            logger.info('pruneVertWeights>> Pruning {}  vertices'.format(len(verts)))

            for v in verts:
                infs = cmds.skinPercent(skinClust, (mesh + ".vtx[" + str(v) + "]"), q=1, v=1)
                active = []
                for inf in infs:
                    if inf > 0.0: active.append(inf)
                active = list(reversed(sorted(active)))
                if debug: print 'Clamping vertex', v, 'to', active[maxInf]
                cmds.skinPercent(skinClust, (mesh + ".vtx[" + str(v) + "]"), pruneWeights=(active[maxInf] * 1.001))
        else:
            cmds.warning('Cannot clamp influences due to locked weights on skinCluster')

    def addJntFn(self):
        sel = cmds.ls(sl=1)
        if len(sel) == 2:
            mesh, jnt = None, None
            for node in sel:
                if cmds.nodeType(node) == 'joint': jnt = node
                if cmds.listRelatives(node, allDescendents=True, noIntermediate=True, fullPath=True, type="mesh"):
                    mesh = node
            if jnt and mesh:
                cmds.skinCluster(self.findRelatedSkinCluster(mesh), e=1, lw=1, wt=0, ai=jnt)
                cmds.setAttr(jnt + '.liw', 0)
            else:
                cmds.warning('skinWrangler: Cannot find joint and mesh in selection: ' + str(sel))

    ## TOOLS TAB
    ########################################################################
    def makeLocOnSel(self):
        tool = cmds.currentCtx()
        cmds.setToolTo('moveSuperContext')
        pos = cmds.manipMoveContext('Move', q=True, p=True)
        startLoc = cmds.spaceLocator(n=('skinWrangler_jointBboxLocator'))[0]
        cmds.move(pos[0], pos[1], pos[2], startLoc, ws=1, a=1)
        cmds.setToolTo(tool)
        return startLoc

    def jointOnBboxCenterFn(self):
        if self.ui.jointOnBboxCenterBTN.isChecked():
            self.ui.jointOnBboxCenterBTN.setText('CREATE JOINT FROM ALIGN LOC')
            self.jointLoc = self.makeLocOnSel()
            cmds.setAttr(self.jointLoc + '.displayLocalAxis', 1)
            cmds.select(self.jointLoc)
        else:
            self.ui.jointOnBboxCenterBTN.setText('MAKE JOINT ON BBOX CENTER')
            locXform = cmds.getAttr(self.jointLoc + '.worldMatrix')

            # get name
            newName = 'createdJoint'
            inputName, ok = QtWidgets.QInputDialog.getText(None, 'Creating Node', 'Enter node name:', text=newName)
            if ok: newName = str(inputName)
            cmds.select(cl=1)
            jnt = cmds.joint(name=newName)
            cmds.xform(jnt, m=locXform)
            cmds.delete(self.jointLoc)

    ## REFRESH UI
    ###############
    def refreshUI(self):
        refInf = self.currentInf
        self.ui.jointLST.clear()
        self.currentInf = refInf

        filter = str(self.ui.filterLINE.text()).lower()

        wid = QtWidgets.QTreeWidgetItem()
        font = wid.font(0)
        font.setWeight(QtGui.QFont.Normal)
        font.setPointSize(8)

        vertSel = True
        s = self.getSelected()
        if s:
            sel, msh, vtx, skin = s
            self.ui.vtxLBL.setText(str(vtx))
        else:
            wid = QtWidgets.QTreeWidgetItem()
            wid.setText(0, 'MAKE A COMPONENT\n SELECTION ON\n SKINNED MESH')
            wid.setFont(0, font)
            self.ui.jointLST.addTopLevelItem(wid)
            cmds.undoInfo(swf=1)
            self.currentInf = None
            vertSel = False

        skin = None
        if self.currentMesh:
            self.ui.mshLBL.setText(self.currentMesh)
        if self.currentSkin:
            self.ui.sknLBL.setText(self.currentSkin)
            skin = self.currentSkin

        if skin:
            # skin method
            m = cmds.skinCluster(skin, q=1, sm=1)
            if m == 0:
                self.ui.skinAlgoLBL.setText('Linear')
            elif m == 1:
                self.ui.skinAlgoLBL.setText('DualQuat')
            elif m == 2:
                self.ui.skinAlgoLBL.setText('Blended')

            # normalization
            n = cmds.skinCluster(skin, q=1, nw=1)
            if n == 0:
                self.ui.skinNormalCMB.setCurrentIndex(n)
                self.currentNormalization = 'None'
            elif n == 1:
                self.ui.skinNormalCMB.setCurrentIndex(n)
                self.currentNormalization = 'Interactive'
            elif n == 2:
                self.ui.skinNormalCMB.setCurrentIndex(n)
                self.currentNormalization = 'Post'

            # max weights
            self.ui.skinMaxInfLBL.setText(str(cmds.skinCluster(skin, q=1, mi=1)))

            if not vertSel:
                return False

            # update jointList
            wDict = self.getAvgVertWeights(sel, skin)
            red = QtGui.QColor(200, 75, 75, 255)
            for inf in wDict.keys():
                if filter in inf.lower() or filter == '':
                    wid = QtWidgets.QTreeWidgetItem()
                    infName = inf
                    if self.ui.nameSpaceCHK.isChecked():
                        infName = inf.split(':')[-1]
                    wid.setText(0, infName)
                    wid.setForeground(0, red)
                    wid.setForeground(1, red)
                    wid.setIcon(0, self.iconLib['joint'])
                    wid.setText(1, str("%.4f" % wDict[inf]))
                    self.ui.jointLST.addTopLevelItem(wid)
            if self.ui.listAllCHK.isChecked():
                for inf in cmds.skinCluster(self.currentSkin, q=1, inf=1):
                    if inf not in wDict.keys() and (filter in inf.lower() or filter == ''):
                        wid = QtWidgets.QTreeWidgetItem()
                        wid.setIcon(0, self.iconLib['joint'])
                        if self.ui.nameSpaceCHK.isChecked():
                            inf = inf.split(':')[-1]
                        wid.setText(0, inf)
                        self.ui.jointLST.addTopLevelItem(wid)

            if self.currentInf:
                for item in self.currentInf:
                    self.getJointFromList(item).setSelected(True)
            logger.info('refreshUI skinWrangler completed.')


if __name__ == '__main__':
    show()
