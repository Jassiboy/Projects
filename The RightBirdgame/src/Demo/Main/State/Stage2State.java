package Demo.Main.State;

import Demo.Main.Entity.Bird;
import Demo.Main.Entity.Entity;
import Demo.Main.Entity.heli;
import Demo.Main.Entity.Mushroom;
import Demo.Main.GamePanel;
import Demo.Main.RandomGenerator;
import Demo.Main.Resources;

import java.applet.AudioClip;
import java.awt.*;
import java.awt.event.KeyEvent;
import java.util.*;

/**
 * Created by jassiboy on 2/26/2017.
 */
public class Stage2State extends State {

    private int logsCrossed = 0;
    private int  background2ImageXcord = 0;
    private java.util.List<heli> helis;
    private java.util.List<Mushroom> Mushrooms;
    private Bird bird;
    private java.util.List<Entity> entities;
    public Stage2State() {
        super();

        helis = new ArrayList<>();
        Mushrooms = new ArrayList<>();
        entities = new ArrayList<>();

        helis.add(new heli(900, 55));
        helis.add(new heli(900, 355));
        Mushrooms.add(new Mushroom(1, 480));
        Mushrooms.add(new Mushroom(224, 480));
        Mushrooms.add(new Mushroom(448, 480));
        Mushrooms.add(new Mushroom(672, 480));
        Mushrooms.add(new Mushroom(896, 480));
        bird = new Bird(200, 50);

        entities.addAll(helis);
        entities.addAll(Mushrooms);
        entities.add(bird);
    }
    @Override
    public void update() {
        for(Entity e: entities) {
            e.update();
        }
        background2ImageXcord -=5;
        for (Mushroom m: Mushrooms) {
            if(m.xCord >930) {
                m.xCord = -210;}
            if(bird.isColldingWith(m)) {
                bird.yVel =- 80;
                bird.yAcc =9;
            }
        }
        for (heli b: helis) {
            if(b.xCord < -20) {
                b.xCord = 980;

                if (RandomGenerator.getInt(0,4) == 0) {
                    b.yCord = 55;
                } else if (RandomGenerator.getInt(0, 5) == 1)
                    b.yCord = 155;
                else if (RandomGenerator.getInt(0,5) == 2)
                    b.yCord=285;
                else {
                    b.yCord=370;
                }




                if(b.visible) {
                    logsCrossed++;

                    if(logsCrossed == 2) {
                        GamePanel.currentState = new Stage3State();
                    }
                }

                b.visible = true;

            }

            if(bird.isColldingWith(b)) {
                bird.xCord  -= 20;
                b.visible = false;
                Resources.flapAudio.play();

            }

            if (background2ImageXcord == -1000)
                background2ImageXcord = 0;
        }

        if(bird.yCord < 0) {
            bird.yCord = 0;
            bird.yVel = 26;
            bird.yAcc = 0;
        }


    }

    @Override
    public void render(Graphics g) {
        g.drawImage(Resources.winterImage, background2ImageXcord, 0, null);
        g.drawImage(Resources.winterImage, background2ImageXcord+1000, 0, null);

        for(Entity e: entities) {
            if(e.visible) {
                g.drawImage(e.getImage(), e.xCord, e.yCord, null);
            }
        }

    }

    @Override
    public void onKeyPressed(int pressedKeyCode) {
        if(pressedKeyCode == KeyEvent.VK_UP ) {
            bird.yVel = -26;
            bird.yAcc = 2;
        } else if (pressedKeyCode == KeyEvent.VK_DOWN) {
            //bird.duck(true);
            bird.yVel = 26;
            bird.yAcc = 2;
        }
    }

    }

